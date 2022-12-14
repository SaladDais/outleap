import asyncio
import html
from typing import *

from PySide6 import QtWidgets
from PySide6.QtCore import QMetaObject
from PySide6.QtUiTools import QUiLoader


class UiLoader(QUiLoader):
    """
    Subclass :class:`~PySide.QtUiTools.QUiLoader` to create the user interface
    in a base instance.

    Unlike :class:`~PySide.QtUiTools.QUiLoader` itself this class does not
    create a new instance of the top-level widget, but creates the user
    interface in an existing instance of the top-level class.

    This mimics the behaviour of :func:`PyQt4.uic.loadUi`.
    """

    def __init__(self, base_instance, custom_widgets=None):
        """
        Create a loader for the given ``baseinstance``.

        The user interface is created in ``baseinstance``, which must be an
        instance of the top-level class in the user interface to load, or a
        subclass thereof.

        ``customWidgets`` is a dictionary mapping from class name to class object
        for widgets that you've promoted in the Qt Designer interface. Usually,
        this should be done by calling registerCustomWidget on the QUiLoader, but
        with PySide 1.1.2 on Ubuntu 12.04 x86_64 this causes a segfault.

        ``parent`` is the parent object of this loader.
        """

        QUiLoader.__init__(self, base_instance)
        self.baseInstance = base_instance
        self.customWidgets = custom_widgets

    def createWidget(self, class_name, parent=None, name=""):
        """
        Function that is called for each widget defined in ui file,
        overridden here to populate baseinstance instead.
        """

        if parent is None and self.baseInstance:
            # supposed to create the top-level widget, return the base instance
            # instead
            return self.baseInstance

        else:
            if class_name in self.availableWidgets():
                # create a new widget for child widgets
                widget = QUiLoader.createWidget(self, class_name, parent, name)

            else:
                # if not in the list of availableWidgets, must be a custom widget
                # this will raise KeyError if the user has not supplied the
                # relevant class_name in the dictionary, or TypeError, if
                # customWidgets is None
                try:
                    widget = self.customWidgets[class_name](parent)

                except (TypeError, KeyError):
                    raise Exception(
                        f"No custom widget {class_name} found in customWidgets param of UiLoader __init__."
                    )

            if self.baseInstance:
                # set an attribute for the new child widget on the base
                # instance, just like PyQt4.uic.loadUi does.
                setattr(self.baseInstance, name, widget)

            return widget


def loadUi(uifile, baseinstance=None, custom_widgets=None, working_directory=None):
    """
    Dynamically load a user interface from the given ``uifile``.

    ``uifile`` is a string containing a file name of the UI file to load.

    If ``baseinstance`` is ``None``, a new instance of the top-level widget
    will be created.  Otherwise, the user interface is created within the given
    ``baseinstance``.  In this case ``baseinstance`` must be an instance of the
    top-level widget class in the UI file to load, or a subclass thereof.  In
    other words, if you've created a ``QMainWindow`` interface in the designer,
    ``baseinstance`` must be a ``QMainWindow`` or a subclass thereof, too.  You
    cannot load a ``QMainWindow`` UI file with a plain
    :class:`~PySide.QtGui.QWidget` as ``baseinstance``.

    ``customWidgets`` is a dictionary mapping from class name to class object
    for widgets that you've promoted in the Qt Designer interface. Usually,
    this should be done by calling registerCustomWidget on the QUiLoader, but
    with PySide 1.1.2 on Ubuntu 12.04 x86_64 this causes a segfault.

    :method:`~PySide.QtCore.QMetaObject.connectSlotsByName()` is called on the
    created user interface, so you can implemented your slots according to its
    conventions in your widget class.

    Return ``baseinstance``, if ``baseinstance`` is not ``None``.  Otherwise
    return the newly created instance of the user interface.
    """

    loader = UiLoader(baseinstance, custom_widgets)

    if working_directory is not None:
        loader.setWorkingDirectory(working_directory)

    widget = loader.load(uifile)
    QMetaObject.connectSlotsByName(widget)
    return widget


def show_error_message(error_msg, parent=None):
    error_dialog = QtWidgets.QErrorMessage(parent=parent)
    # No obvious way to set this to plaintext, yuck...
    error_dialog.showMessage(html.escape(error_msg))
    error_dialog.exec()
    error_dialog.raise_()


class GUIInteractionManager:
    def __init__(self, parent: QtWidgets.QWidget):
        self._parent = parent

    def _dialog_async_exec(self, dialog: QtWidgets.QDialog):
        future = asyncio.Future()
        dialog.finished.connect(lambda r: future.set_result(r))
        dialog.open()
        return future

    async def _file_dialog(
        self,
        caption: str,
        directory: str,
        filter_str: str,
        mode: QtWidgets.QFileDialog.FileMode,
        default_suffix: str = "",
    ) -> Tuple[bool, QtWidgets.QFileDialog]:
        dialog = QtWidgets.QFileDialog(self._parent, caption=caption, directory=directory, filter=filter_str)
        dialog.setFileMode(mode)
        if mode == QtWidgets.QFileDialog.FileMode.AnyFile:
            dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        if default_suffix:
            dialog.setDefaultSuffix(default_suffix)
        res = await self._dialog_async_exec(dialog)
        return res, dialog

    async def open_files(self, caption: str = "", directory: str = "", filter_str: str = "") -> List[str]:
        res, dialog = await self._file_dialog(
            caption, directory, filter_str, QtWidgets.QFileDialog.FileMode.ExistingFiles
        )
        if not res:
            return []
        return dialog.selectedFiles()

    async def open_file(self, caption: str = "", directory: str = "", filter_str: str = "") -> Optional[str]:
        res, dialog = await self._file_dialog(
            caption, directory, filter_str, QtWidgets.QFileDialog.FileMode.ExistingFile
        )
        if not res:
            return None
        return dialog.selectedFiles()[0]

    async def open_dir(self, caption: str = "", directory: str = "", filter_str: str = "") -> Optional[str]:
        res, dialog = await self._file_dialog(
            caption, directory, filter_str, QtWidgets.QFileDialog.FileMode.Directory
        )
        if not res:
            return None
        return dialog.selectedFiles()[0]

    async def save_file(
        self, caption: str = "", directory: str = "", filter_str: str = "", default_suffix: str = ""
    ) -> Optional[str]:
        res, dialog = await self._file_dialog(
            caption,
            directory,
            filter_str,
            QtWidgets.QFileDialog.FileMode.AnyFile,
            default_suffix,
        )
        if not res or not dialog.selectedFiles():
            return None
        return dialog.selectedFiles()[0]

    async def confirm(self, title: str, caption: str) -> bool:
        msg = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Icon.Question,
            title,
            caption,
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            self._parent,
        )
        fut = asyncio.Future()
        msg.finished.connect(lambda r: fut.set_result(r))
        msg.open()
        return (await fut) == QtWidgets.QMessageBox.Ok
