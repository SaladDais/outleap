import asyncio
import enum
import logging
import signal
import sys
import weakref
from typing import *

import pkg_resources
from PySide6 import QtCore, QtWidgets
from qasync import QEventLoop, asyncSlot

import outleap
from outleap import LEAPClient, UIElement, UIPath
from outleap.qt_helpers import loadUi

ROOT_LOG = logging.getLogger()
ROOT_LOG.addHandler(logging.StreamHandler())
ROOT_LOG.setLevel(logging.DEBUG)
LOG = logging.getLogger(__name__)


def get_resource_filename(resource_filename: str):
    return pkg_resources.resource_filename("outleap", resource_filename)


class ElemTreeHeader(enum.IntEnum):
    Name = 0


MAIN_WINDOW_UI_PATH = get_resource_filename("scripts/ui/inspector.ui")


class LEAPInspectorGUI(QtWidgets.QMainWindow):
    lineEditFind: QtWidgets.QLineEdit
    treeElems: QtWidgets.QTreeWidget
    labelElemScreenshot: QtWidgets.QLabel
    textElemProperties: QtWidgets.QTextEdit
    btnRefresh: QtWidgets.QPushButton

    def __init__(self, client: outleap.LEAPClient):
        super().__init__()

        loadUi(MAIN_WINDOW_UI_PATH, self)

        self.client = client
        self._filter = ""
        self.window_api = outleap.LLWindowAPI(client)
        self.element_tree = outleap.UIElementTree(self.window_api)
        self.pathToItem: Dict[UIPath, QtWidgets.QTreeWidgetItem] = weakref.WeakValueDictionary()  # noqa

        self.treeElems.setColumnCount(len(ElemTreeHeader))
        self.treeElems.setHeaderLabels(tuple(x.name for x in ElemTreeHeader))
        self.treeElems.header().setStretchLastSection(True)
        self.btnRefresh.clicked.connect(self.reloadFromTree)
        self.lineEditFind.editingFinished.connect(self.filterChanged)

    @asyncSlot()
    async def reloadFromTree(self):
        self.treeElems.clear()
        self.pathToItem.clear()

        await self.element_tree.refresh()

        self.treeElems.setUpdatesEnabled(False)
        self._addChildren(self.element_tree.root_children, self.treeElems.invisibleRootItem())
        self.applyFilter()
        self.treeElems.setUpdatesEnabled(True)

        self.treeElems.sortByColumn(ElemTreeHeader.Name, QtCore.Qt.AscendingOrder)
        self.treeElems.selectionModel().selectionChanged.connect(self._blockSelected)

    def filterChanged(self):
        self._filter = self.lineEditFind.text()
        self.applyFilter()

    def applyFilter(self):
        filter_Text = self._filter.lower()

        def _set_path_item_hidden(path: UIPath, hidden: bool):
            item = self.pathToItem.get(path)
            if item is not None:
                item.setHidden(hidden)
                # Only modify item expansion values if we actually specified
                # a filter. Don't contract everything if we clear out a filter,
                # so it's easy to see previously-filtered items in their full
                # context.
                if filter_Text:
                    item.setExpanded(bool(filter_Text and not hidden))

        def _unhide_ancestry(path: UIPath):
            _set_path_item_hidden(path, False)
            if path.parent != path:
                _unhide_ancestry(path.parent)

        self.treeElems.setUpdatesEnabled(False)
        for elem in self.element_tree:
            _set_path_item_hidden(elem, True)

        for path in self.element_tree:
            if filter_Text in path.stem.lower():
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
            self.pathToItem[node.path] = item
            items.append(item)
            self._addChildren(node.children, item)
        parent.addChildren(items)

    @asyncSlot()
    async def _blockSelected(self, selected, deselected):
        self.textElemProperties.setPlainText("")
        indexes = selected.indexes()
        if len(indexes):
            index = indexes[ElemTreeHeader.Name]
            path = index.data(QtCore.Qt.UserRole)
            elem = self.element_tree[path]
            await elem.refresh()
            elem_str = ""
            for k, v in elem.to_dict().items():
                elem_str += f"{k}: {v}\n"
            self.textElemProperties.setPlainText(elem_str)
            print(elem_str, file=sys.stderr)
        else:
            print("none selected", file=sys.stderr)


async def start_gui():
    signal.signal(signal.SIGINT, lambda *args: QtWidgets.QApplication.quit())
    client = await LEAPClient.create_stdio_client()
    window = LEAPInspectorGUI(client)
    window.show()


def inspector_main():
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
