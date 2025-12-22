"""
Base Page Class for Wizard Steps
Provides common functionality for all wizard pages
"""

from typing import Dict, Any, Optional, Tuple
try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
        QFrame, QScrollArea, QSizePolicy
    )
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QFont
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QFrame, QScrollArea, QSizePolicy
    )
    from PyQt5.QtCore import Qt, pyqtSignal as Signal
    from PyQt5.QtGui import QFont


class BasePage(QWidget):
    """Base class for all wizard pages"""
    
    validation_changed = Signal(bool)
    data_changed = Signal()
    
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.page_title = title
        self.page_subtitle = subtitle
        self._setup_base_layout()
    
    def _setup_base_layout(self):
        """Set up the base page layout with header and scrollable content"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        header = QWidget()
        header.setObjectName("page-header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 12)
        
        title_label = QLabel(self.page_title)
        title_label.setProperty("class", "page-title")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #e6edf3; font-size: 22px; font-weight: 600;")
        header_layout.addWidget(title_label)
        
        if self.page_subtitle:
            subtitle_label = QLabel(self.page_subtitle)
            subtitle_label.setProperty("class", "page-subtitle")
            subtitle_label.setStyleSheet("color: #8b949e; font-size: 12px; margin-top: 6px;")
            subtitle_label.setWordWrap(True)
            header_layout.addWidget(subtitle_label)
        
        main_layout.addWidget(header)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 16, 16)
        self.content_layout.setSpacing(12)
        
        scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(scroll_area, 1)
    
    def create_section_header(self, text: str) -> QLabel:
        """Create a styled section header"""
        label = QLabel(text)
        label.setStyleSheet("""
            color: #e6edf3;
            font-size: 13px;
            font-weight: 600;
            margin-top: 10px;
            margin-bottom: 6px;
        """)
        return label
    
    def create_helper_text(self, text: str) -> QLabel:
        """Create helper/description text"""
        label = QLabel(text)
        label.setStyleSheet("color: #8b949e; font-size: 11px;")
        label.setWordWrap(True)
        return label
    
    def create_separator(self) -> QFrame:
        """Create a horizontal separator line"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #30363d;")
        line.setFixedHeight(1)
        return line
    
    def create_card(self) -> QFrame:
        """Create a styled card container with gradient background"""
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(13, 42, 58, 0.9),
                    stop:1 rgba(15, 58, 79, 0.9));
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: 8px;
                padding: 12px;
            }
        """)
        return card
    
    def create_warning_box(self, title: str, message: str) -> QFrame:
        """Create a warning message box"""
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background-color: rgba(28, 28, 23, 0.9);
                border: 1px solid #9e6a03;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        layout = QVBoxLayout(box)
        layout.setSpacing(6)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #d29922; font-weight: 600; font-size: 12px;")
        layout.addWidget(title_label)
        
        msg_label = QLabel(message)
        msg_label.setStyleSheet("color: #d29922; font-size: 11px;")
        msg_label.setWordWrap(True)
        layout.addWidget(msg_label)
        
        return box
    
    def create_validation_label(self) -> QLabel:
        """Create a validation error label"""
        label = QLabel()
        label.setStyleSheet("color: #f85149; font-size: 11px;")
        label.hide()
        return label
    
    def show_validation_error(self, label: QLabel, message: str):
        """Show validation error on a label"""
        label.setText(message)
        label.setStyleSheet("color: #f85149; font-size: 11px;")
        label.show()
    
    def show_validation_success(self, label: QLabel, message: str):
        """Show validation success on a label"""
        label.setText(message)
        label.setStyleSheet("color: #00d4ff; font-size: 11px;")
        label.show()
    
    def hide_validation(self, label: QLabel):
        """Hide validation label"""
        label.hide()
    
    def validate(self) -> Tuple[bool, str]:
        """
        Validate the page data.
        Override in subclasses.
        Returns (is_valid, error_message)
        """
        return True, ""
    
    def get_data(self) -> Dict[str, Any]:
        """
        Get the page data.
        Override in subclasses.
        """
        return {}
    
    def set_data(self, data: Dict[str, Any]):
        """
        Set the page data (for loading saved state).
        Override in subclasses.
        """
        pass
    
    def on_enter(self):
        """Called when entering the page. Override in subclasses."""
        pass
    
    def on_leave(self):
        """Called when leaving the page. Override in subclasses."""
        pass
    
    def can_skip(self) -> bool:
        """Whether this page can be skipped. Override in subclasses."""
        return False
