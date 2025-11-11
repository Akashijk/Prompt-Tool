"""A mixin class to provide smooth scrolling for Qt widgets."""
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QWidget

class SmoothScrollMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scroll_animation = QPropertyAnimation()
        self._scroll_animation.setTargetObject(self.verticalScrollBar())
        self._scroll_animation.setPropertyName(b"value")
        self._scroll_animation.setDuration(250)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.scroll_speed_factor = 2 # Adjust this value to change scroll speed

    def wheelEvent(self, event):
        if self._scroll_animation.state() == QPropertyAnimation.Running:
            return

        delta = event.angleDelta().y() * self.scroll_speed_factor
        current_value = self.verticalScrollBar().value()
        new_value = current_value - delta

        self._scroll_animation.setStartValue(current_value)
        self._scroll_animation.setEndValue(new_value)
        self._scroll_animation.start()
