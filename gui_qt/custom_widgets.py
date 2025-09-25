"""Custom Qt widgets with specialized behavior."""

from PySide6.QtWidgets import QTextBrowser
from PySide6.QtGui import QMouseEvent, QTextCursor

class LinkOnlyTextBrowser(QTextBrowser):
    """
    A custom QTextBrowser that only processes mouse clicks on anchors (links),
    preventing unwanted behavior when clicking on empty areas.
    """
    def mousePressEvent(self, event: QMouseEvent):
        """Overrides the default mouse press event."""
        # We take full control here. We check for an anchor and if found,
        # we manually emit the anchorClicked signal. We do NOT call the parent
        # implementation, which prevents the browser from trying to navigate
        # or change its internal state, thus avoiding the "No document" error.
        self.anchor = self.anchorAt(event.pos())
        if self.anchor:
            # The event is accepted, but we don't pass it to the parent.
            event.accept()
        else:
            # If not on a link, we explicitly ignore it.
            event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Overrides the default mouse release event."""
        # If a press event started on an anchor, and the release is also on
        # that same anchor, we emit the signal.
        if self.anchor and self.anchor == self.anchorAt(event.pos()):
            self.anchorClicked.emit(self.anchor)
        self.anchor = None # Reset the anchor state.