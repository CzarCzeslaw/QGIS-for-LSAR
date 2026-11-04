from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from .dock import text_label


class LkpDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zapisz lokalizację jako LKP")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(
            text_label(
                result.label
                + "\nTyp wyniku: "
                + result.kind
                + ". Sprawdź, czy wskazuje właściwe miejsce."
            )
        )
        form = QFormLayout()
        self.name = QLineEdit("LKP")
        self.source = QLineEdit()
        self.source.setPlaceholderText("Skąd pochodzi informacja o lokalizacji osoby?")
        self.confidence = QComboBox()
        self.confidence.addItems(["nieokreślona", "niska", "średnia", "wysoka"])
        self.time_known = QCheckBox("Znam czas zdarzenia / obserwacji")
        self.time = QDateTimeEdit(QDateTime.currentDateTime())
        self.time.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.time.setCalendarPopup(True)
        self.time.setEnabled(False)
        self.time_known.toggled.connect(self.time.setEnabled)
        self.notes = QPlainTextEdit()
        form.addRow("Nazwa", self.name)
        form.addRow("Źródło informacji", self.source)
        form.addRow("Pewność", self.confidence)
        form.addRow(self.time_known)
        form.addRow("Czas lokalny", self.time)
        form.addRow("Uwagi", self.notes)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Zapisz LKP")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.source.textChanged.connect(self.validate)
        self.name.textChanged.connect(self.validate)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def validate(self):
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(
            bool(self.source.text().strip() and self.name.text().strip())
        )

    def details(self):
        return {
            "name": self.name.text().strip(),
            "source": self.source.text().strip(),
            "confidence": self.confidence.currentText(),
            "observed_at": self.time.dateTime().toUTC() if self.time_known.isChecked() else None,
            "notes": self.notes.toPlainText().strip(),
        }
