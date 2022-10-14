import asyncio
import contextlib
import enum
import logging
import os
import signal
import sys
import tempfile
import weakref
from typing import *

import pkg_resources
from PySide6 import QtCore, QtGui, QtWidgets
from qasync import QEventLoop, asyncSlot

import outleap
from outleap import LEAPClient, UIElement, UIPath
from outleap.qt_helpers import GUIInteractionManager, loadUi

LOG = logging.getLogger(__name__)


def get_resource_filename(resource_filename: str):
    return pkg_resources.resource_filename("outleap", resource_filename)


class ElemTreeHeader(enum.IntEnum):
    Name = 0


MAIN_WINDOW_UI_PATH = get_resource_filename("scripts/ui/inspector.ui")


@contextlib.contextmanager
def temp_file_path():
    """Create a temporary file, yielding path and deleting it after"""
    # Windows NT can't have two open FHs on a tempfile, so we need
    # handle deletion ourselves :/
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.close()
        try:
            yield f.name
        finally:
            os.remove(f.name)


def _calc_clipped_rect(pix: QtGui.QPixmap, elem: outleap.UIElement) -> QtCore.QRect:
    base_rect = _elem_rect_to_qrect(pix, elem.rect)
    while elem := elem.parent:
        # Should also be clipped to the intersection of all parent rects,
        # some scrollers have offscreen rects that can't really be shown
        # in a screenshot.
        parent_rect = _elem_rect_to_qrect(pix, elem.rect)
        base_rect = base_rect.intersected(parent_rect)
    return base_rect


def _elem_rect_to_qrect(pix: QtGui.QPixmap, rect: outleap.UIRect) -> QtCore.QRect:
    # SL y origin is at the bottom, but Qt wants it at the top!
    # Need pixmap dimensions to convert.
    return QtCore.QRect(
        rect.left,
        pix.height() - rect.top,
        max(0, rect.right - rect.left),
        max(0, rect.top - rect.bottom),
    )


class LEAPInspectorGUI(QtWidgets.QMainWindow):
    lineEditFind: QtWidgets.QLineEdit
    treeElems: QtWidgets.QTreeWidget
    labelElemScreenshot: QtWidgets.QLabel
    textElemProperties: QtWidgets.QTextEdit
    btnRefresh: QtWidgets.QPushButton
    btnClickElem: QtWidgets.QPushButton
    btnSaveRendered: QtWidgets.QPushButton
    graphicsElemScreenshot: QtWidgets.QGraphicsView

    def __init__(self, client: outleap.LEAPClient):
        super().__init__()

        loadUi(MAIN_WINDOW_UI_PATH, self)

        self.client = client
        self._filter = ""

        self.interaction_manager = GUIInteractionManager(self)
        self.window_api = outleap.LLWindowAPI(client)
        self.viewer_window_api = outleap.LLViewerWindowAPI(self.client)
        self._element_tree = outleap.UIElementTree(self.window_api)
        self._items_by_path: Dict[UIPath, QtWidgets.QTreeWidgetItem] = weakref.WeakValueDictionary()  # noqa

        self.treeElems.setColumnCount(len(ElemTreeHeader))
        self.treeElems.setHeaderLabels(tuple(x.name for x in ElemTreeHeader))
        self.treeElems.header().setStretchLastSection(True)
        self.treeElems.selectionModel().selectionChanged.connect(self.updateSelectedElemInfo)
        self.btnRefresh.clicked.connect(self.reloadFromTree)
        self.lineEditFind.editingFinished.connect(self.filterChanged)

        self.btnClickElem.clicked.connect(self.clickElem)
        self.btnSaveRendered.clicked.connect(self.saveRendered)

        self.sceneElemScreenshot = QtWidgets.QGraphicsScene()
        self.graphicsElemScreenshot.setScene(self.sceneElemScreenshot)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        # Don't need to create_task() because this is an `asyncSlot()`
        self.reloadFromTree()
        return super().showEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            self.client.disconnect()
        except Exception as e:
            logging.exception(e)
        return super().closeEvent(event)

    def _getSelectedPath(self) -> Optional[UIPath]:
        if selected := self.treeElems.selectedItems():
            return selected[0].data(ElemTreeHeader.Name, QtCore.Qt.UserRole)
        return None

    @asyncSlot()
    async def reloadFromTree(self):
        selected_path = self._getSelectedPath()

        self.treeElems.clear()
        self._items_by_path.clear()

        await self._element_tree.refresh()

        self.treeElems.setUpdatesEnabled(False)
        self._addChildren(self._element_tree.root_children, self.treeElems.invisibleRootItem())
        self.applyFilter()
        self.treeElems.setUpdatesEnabled(True)

        self.treeElems.sortByColumn(ElemTreeHeader.Name, QtCore.Qt.AscendingOrder)

        if selected_path and selected_path in self._items_by_path:
            item = self._items_by_path[selected_path]
            self.treeElems.scrollToItem(item)
            self.treeElems.setCurrentItem(item)

    def filterChanged(self):
        self._filter = self.lineEditFind.text()
        self.applyFilter()

    def applyFilter(self):
        filter_text = self._filter.lower()

        def _set_path_item_hidden(path: UIPath, hidden: bool):
            item = self._items_by_path.get(path)
            if item is not None:
                item.setHidden(hidden)
                # Only modify item expansion values if we actually specified
                # a filter. Don't contract everything if we clear out a filter,
                # so it's easy to see previously-filtered items in their full
                # context.
                if filter_text:
                    item.setExpanded(bool(filter_text and not hidden))

        def _unhide_ancestry(path: UIPath):
            _set_path_item_hidden(path, False)
            if path.parent != path:
                _unhide_ancestry(path.parent)

        self.treeElems.setUpdatesEnabled(False)
        for elem in self._element_tree:
            _set_path_item_hidden(elem, True)

        for path in self._element_tree:
            if filter_text in path.stem.lower():
                _unhide_ancestry(path)
        self.treeElems.setUpdatesEnabled(True)

        # Make it easier to find what was selected before the filter changed
        selected = self.treeElems.selectedItems()
        if selected and not selected[0].isHidden():
            self.treeElems.scrollToItem(selected[0])

    def _addChildren(self, nodes: Sequence[UIElement], parent: QtWidgets.QTreeWidgetItem):
        items = []
        # Batch up everything so that we can add it all to the tree at once.
        for node in nodes:
            # The type signature implies `None` is wrong here, but it isn't.
            item = QtWidgets.QTreeWidgetItem(None, [node.path.stem])  # noqa
            item.setData(ElemTreeHeader.Name, QtCore.Qt.UserRole, node.path)
            self._items_by_path[node.path] = item
            items.append(item)
            self._addChildren(node.children, item)
        parent.addChildren(items)

    @asyncSlot()
    async def updateSelectedElemInfo(self, *args):
        self.textElemProperties.setPlainText("")
        self.btnClickElem.setEnabled(False)
        self.btnSaveRendered.setEnabled(False)
        self.sceneElemScreenshot.clear()

        if not (selected_path := self._getSelectedPath()):
            return
        self.btnClickElem.setEnabled(True)

        # Display some info about the element this item refers to
        elem = self._element_tree[selected_path]
        # Refresh info for the element and its ancestors (we need updated rects)
        await asyncio.gather(*[e.refresh() for e in [elem, *elem.ancestors]])

        elem_str = ""
        for k, v in elem.to_dict().items():
            elem_str += f"{k}: {v}\n"
        self.textElemProperties.setPlainText(elem_str)
        print(elem_str, file=sys.stderr)

        # This is either an incomplete or invisible element, we can't show a preview.
        if not elem.info or not elem.visible_chain:
            return

        self.btnSaveRendered.setEnabled(True)

        # Draw the element preview
        # TODO: this is wasteful, cache screenshot pixmap for `n` seconds?
        pix_screenshot = QtGui.QPixmap()
        with temp_file_path() as path:
            await self.viewer_window_api.save_snapshot(path)
            pix_screenshot.load(path)

        # Clip scene and view to elem rect
        scene_rect = _calc_clipped_rect(pix_screenshot, elem)
        self.sceneElemScreenshot.addPixmap(pix_screenshot)
        self.sceneElemScreenshot.setSceneRect(scene_rect)
        self.graphicsElemScreenshot.fitInView(scene_rect, QtCore.Qt.KeepAspectRatio)

    @asyncSlot()
    async def clickElem(self):
        if not (selected_path := self._getSelectedPath()):
            return
        await self.window_api.mouse_click(path=selected_path, button="LEFT")
        # We clicked, which may have had an effect on the UI state.
        await self.updateSelectedElemInfo()

    @asyncSlot()
    async def saveRendered(self):
        if not (selected_path := self._getSelectedPath()):
            return
        elem = self._element_tree[selected_path]
        pix_screenshot = QtGui.QPixmap()
        with temp_file_path() as path:
            await self.viewer_window_api.save_snapshot(path)
            pix_screenshot.load(path)
        # Make a clipped copy of the screenshot
        clipped = pix_screenshot.copy(_calc_clipped_rect(pix_screenshot, elem))

        file_name = await self.interaction_manager.save_file(
            caption="Save Rendered Element", filter_str="PNG Images (*.png)", default_suffix="png"
        )
        if not file_name:
            return
        clipped.save(file_name, "PNG")


async def start_gui():
    signal.signal(signal.SIGINT, lambda *args: QtWidgets.QApplication.quit())
    client = await LEAPClient.create_stdio_client()
    window = LEAPInspectorGUI(client)
    window.show()


def inspector_main():
    logging.basicConfig()
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    loop: asyncio.AbstractEventLoop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    print(
        "Running in direct LEAP execution mode.\n"
        "If you're seeing this anywhere other than the viewer logs, "
        "you probably messed up, the viewer should be executing this!\n"
        "Try adding a '--tcp' argument!",
        file=sys.stderr,
    )

    loop.run_until_complete(start_gui())
    loop.run_forever()


if __name__ == "__main__":
    inspector_main()
