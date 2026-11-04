from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


def text_label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def page(tabs, title):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(widget)
    tabs.addTab(scroll, title)
    return widget, layout


class SarDock(QDockWidget):
    create_requested = pyqtSignal(str, str)
    open_requested = pyqtSignal()
    save_requested = pyqtSignal()
    restore_requested = pyqtSignal()
    maps_requested = pyqtSignal(list)
    cancel_maps_requested = pyqtSignal()
    visibility_requested = pyqtSignal(str, bool)
    opacity_requested = pyqtSignal(str, int)
    search_requested = pyqtSignal(str)
    cancel_search_requested = pyqtSignal()
    locate_requested = pyqtSignal(int)
    lkp_requested = pyqtSignal(int)
    dem_requested = pyqtSignal()
    profile_requested = pyqtSignal()
    link_requested = pyqtSignal(str)
    diagnostic_requested = pyqtSignal()
    health_requested = pyqtSignal()
    developer_changed = pyqtSignal(bool)

    def __init__(self, sources, parent=None):
        super().__init__("SAR Tools · 0.1", parent)
        self.setObjectName("SarToolsDock")
        self.setMinimumWidth(400)
        self.sources = {s["id"]: s for s in sources}
        self.source_items = {}
        self.syncing = False
        body = QWidget()
        layout = QVBoxLayout(body)
        self.operation_label = text_label("Brak otwartej operacji SAR")
        self.operation_label.setStyleSheet("font-weight: 600; padding: 8px;")
        layout.addWidget(self.operation_label)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.message = text_label("Utwórz operację lub otwórz zapisany projekt.")
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.message)
        self.setWidget(body)
        self._project_page()
        self._maps_page(sources)
        self._location_page()
        self._modules_page()
        self._settings_page()

    def button(self, layout, title, callback):
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _project_page(self):
        _, layout = page(self.tabs, "Projekt")
        layout.addWidget(
            text_label("Nowa operacja tworzy projekt, warstwy robocze oraz osobny folder na dane.")
        )
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(100)
        self.name_edit.setPlaceholderText("Nazwa operacji")
        form.addRow("Nazwa", self.name_edit)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder nadrzędny operacji")
        form.addRow("Folder", self.folder_edit)
        layout.addLayout(form)
        self.button(layout, "Wybierz folder…", self.choose_folder)
        self.auto_maps = QCheckBox("Dodaj katalog map po utworzeniu operacji")
        self.auto_maps.setChecked(True)
        layout.addWidget(self.auto_maps)
        self.button(
            layout,
            "Utwórz operację",
            lambda: self.create_requested.emit(self.folder_edit.text(), self.name_edit.text()),
        )
        self.button(layout, "Otwórz operację…", self.open_requested.emit)
        self.button(layout, "Zapisz projekt", self.save_requested.emit)
        self.button(layout, "Przywróć brakujące grupy i warstwy", self.restore_requested.emit)
        layout.addWidget(
            text_label(
                "Planowanie • Do GPS • Z GPS • Mapy i teren\n\n"
                "Warstwy planistyczne edytujesz standardowymi narzędziami QGIS. "
                "Edycje danych zapisuj przyciskiem zapisu warstwy."
            )
        )
        layout.addStretch()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Folder nadrzędny operacji", self.folder_edit.text()
        )
        if path:
            self.folder_edit.setText(path)

    def _maps_page(self, sources):
        _, layout = page(self.tabs, "Mapy")
        self.map_tabs = QTabWidget()
        layout.addWidget(self.map_tabs)
        _, catalogue = page(self.map_tabs, "Katalog")
        catalogue.addWidget(
            text_label(
                "Zaznaczenie włącza dodaną mapę. Wybierz pozycję i kliknij "
                "„Dodaj / ponów”, aby pobrać brakujące źródło. "
                "W grupie podkładów widoczna jest jedna mapa naraz."
            )
        )
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Źródło", "Stan"])
        self.tree.setColumnWidth(0, 245)
        self.tree.setMinimumHeight(220)
        catalogue.addWidget(self.tree)
        groups = {}
        for key, title in (
            ("forest", "Lasy"),
            ("relief", "Rzeźba terenu"),
            ("basemaps", "Podkłady"),
        ):
            groups[key] = QTreeWidgetItem(self.tree, [title])
        for source in sources:
            item = QTreeWidgetItem(groups[source["group"]], [source["name"], "Do dodania"])
            item.setData(0, Qt.ItemDataRole.UserRole, source["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setToolTip(
                0, source["name"] + "\n" + source["attribution"] + "\n" + source["documentation"]
            )
            self.source_items[source["id"]] = item
        self.tree.expandAll()
        self.tree.itemChanged.connect(self._visibility)
        self.button(catalogue, "Dodaj / ponów wybraną mapę", self.add_selected)
        self.button(
            catalogue,
            "Dodaj wszystkie brakujące mapy",
            lambda: self.maps_requested.emit(list(self.sources)),
        )
        self.button(catalogue, "Anuluj dodawanie map", self.cancel_maps_requested.emit)
        self.map_progress = QProgressBar()
        self.map_progress.setRange(0, 1)
        self.map_progress.setValue(0)
        catalogue.addWidget(self.map_progress)
        catalogue.addWidget(text_label("Krycie wybranej mapy"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        catalogue.addWidget(self.opacity)
        self.tree.currentItemChanged.connect(self._select_source)
        self.opacity.valueChanged.connect(self._opacity)
        self.opacity_values = {s["id"]: round(s["opacity"] * 100) for s in sources}
        self.attributions = text_label(
            "Źródła: GUGiK • Bank Danych o Lasach • © OpenStreetMap contributors"
        )
        catalogue.addWidget(self.attributions)
        _, terrain = page(self.map_tabs, "Wysokości")
        terrain.addWidget(
            text_label(
                "Do profili potrzebny jest raster z wysokościami. "
                "Cieniowanie z Geoportalu jest obrazem mapy.\n\n"
                "Wczytaj pobrany NMT GUGiK, NASADEM lub SRTM. "
                "Wskaż poprawne pasmo wysokościowe; jednostką powinien być metr."
            )
        )
        self.button(terrain, "Dodaj lokalny model wysokości…", self.dem_requested.emit)
        self.button(terrain, "Otwórz profil terenu QGIS", self.profile_requested.emit)
        terrain.addWidget(
            text_label(
                "W panelu profilu narysuj linię na mapie i wybierz dodany raster. "
                "Dane wysokościowe pozostają w swojej lokalizacji na dysku."
            )
        )
        self.button(terrain, "Źródła NMT GUGiK", lambda: self.link_requested.emit("nmt"))
        self.button(terrain, "Źródła NASADEM / SRTM", lambda: self.link_requested.emit("nasa"))
        terrain.addStretch()
        _, google = page(self.map_tabs, "Google")
        google.addWidget(
            text_label(
                "Google Maps można otworzyć dla bieżącego widoku w przeglądarce.\n\n"
                "Podkład wewnątrz QGIS: planowana integracja z oficjalnym API, "
                "wymagająca klucza i konta rozliczeniowego. "
                "Dla nowych projektów EOG Map Tiles API nie udostępnia "
                "satelitarnych kafelków 2D."
            )
        )
        self.button(
            google, "Otwórz ten obszar w Google Maps", lambda: self.link_requested.emit("google")
        )
        unavailable = self.button(google, "Podkład Google w QGIS — planowane", lambda: None)
        unavailable.setEnabled(False)
        self.button(
            google, "Warunki integracji Google", lambda: self.link_requested.emit("google_docs")
        )
        google.addStretch()

    def selected_source(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def add_selected(self):
        source = self.selected_source()
        if source:
            self.maps_requested.emit([source])

    def _visibility(self, item, column):
        source = item.data(0, Qt.ItemDataRole.UserRole)
        if source and not self.syncing and column == 0:
            self.visibility_requested.emit(source, item.checkState(0) == Qt.CheckState.Checked)

    def _select_source(self, *_):
        source = self.selected_source()
        self.opacity.blockSignals(True)
        self.opacity.setValue(self.opacity_values.get(source, 100))
        self.opacity.blockSignals(False)

    def _opacity(self, value):
        source = self.selected_source()
        if source:
            self.opacity_values[source] = value
            self.opacity_requested.emit(source, value)

    def map_status(self, source, status):
        if source in self.source_items:
            self.source_items[source].setText(1, status)
            self.source_items[source].setToolTip(1, status)

    def sync_maps(self, layers, tree_root):
        self.syncing = True
        try:
            loaded = {layer.customProperty("sar/source", ""): layer for layer in layers}
            for key, item in self.source_items.items():
                layer = loaded.get(key)
                node = tree_root.findLayer(layer.id()) if layer else None
                item.setCheckState(
                    0,
                    Qt.CheckState.Checked if node and node.isVisible() else Qt.CheckState.Unchecked,
                )
                if layer:
                    item.setText(1, "Dodano" if layer.isValid() else "Źródło niedostępne")
                    self.opacity_values[key] = (
                        round(layer.renderer().opacity() * 100) if layer.renderer() else 100
                    )
        finally:
            self.syncing = False

    def progress(self, done, total):
        self.map_progress.setRange(0, max(1, total))
        self.map_progress.setValue(done)
        self.map_progress.setFormat("%v / %m map" if total else "Brak zadań")

    def _location_page(self):
        _, layout = page(self.tabs, "Adres")
        layout.addWidget(
            text_label(
                "Wyszukaj adres w Polsce. Zapytanie zostanie wysłane do GUGiK "
                "dopiero po kliknięciu „Szukaj”."
            )
        )
        self.query = QLineEdit()
        self.query.setPlaceholderText("np. Marki, Andersa 1")
        self.query.setMaxLength(250)
        layout.addWidget(self.query)
        self.query.returnPressed.connect(lambda: self.search_requested.emit(self.query.text()))
        row = QHBoxLayout()
        self.search_button = self.button(
            row, "Szukaj", lambda: self.search_requested.emit(self.query.text())
        )
        self.button(row, "Anuluj", self.cancel_search_requested.emit)
        layout.addLayout(row)
        self.search_status = text_label(
            "Wynik może wskazywać adres, ulicę lub środek miejscowości."
        )
        layout.addWidget(self.search_status)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        layout.addWidget(self.results)
        self.results.itemDoubleClicked.connect(
            lambda _: self.locate_requested.emit(self.results.currentRow())
        )
        self.button(
            layout,
            "Pokaż wynik na mapie",
            lambda: self.locate_requested.emit(self.results.currentRow()),
        )
        self.button(
            layout,
            "Zapisz wybrany wynik jako LKP…",
            lambda: self.lkp_requested.emit(self.results.currentRow()),
        )
        layout.addWidget(
            text_label(
                "Wyszukanie adresu nie tworzy automatycznie LKP. "
                "Zapisanie wymaga podania informacji o zdarzeniu."
            )
        )

    def search_busy(self, busy):
        self.search_button.setEnabled(not busy)
        self.search_status.setText("Wyszukiwanie…" if busy else "Gotowe")

    def show_results(self, results):
        self.results.clear()
        for result in results:
            self.results.addItem(result.label + "\nTyp lokalizacji: " + result.kind)
        self.search_status.setText(
            "Wyniki: " + str(len(results))
            if results
            else "Nie znaleziono adresu. Doprecyzuj miejscowość, ulicę lub numer."
        )
        if results:
            self.results.setCurrentRow(0)

    def _modules_page(self):
        _, layout = page(self.tabs, "Moduły")
        layout.addWidget(
            text_label(
                "Wersja 0.1 przygotowuje strukturę danych. "
                "Funkcje poniżej zostaną udostępnione w kolejnych wersjach."
            )
        )
        for title in (
            "Wyślij do GPS",
            "Importuj z GPS / FIT / GPX",
            "Analiza śladów",
            "Analiza terenu",
            "Model ruchu i izochrony",
            "Automatyczne planowanie",
            "Mapy offline",
            "Telekomunikacja / BTS",
            "Eksport i raporty",
        ):
            button = self.button(layout, title + " — planowane", lambda: None)
            button.setEnabled(False)
        layout.addStretch()

    def _settings_page(self):
        _, layout = page(self.tabs, "Opcje")
        self.developer = QCheckBox("Tryb deweloperski — dodatkowe informacje diagnostyczne")
        self.developer.toggled.connect(self.developer_changed.emit)
        layout.addWidget(self.developer)
        self.health_label = text_label("")
        layout.addWidget(self.health_label)
        self.button(layout, "Sprawdź środowisko", self.health_requested.emit)
        self.button(layout, "Eksportuj pakiet diagnostyczny…", self.diagnostic_requested.emit)
        layout.addWidget(
            text_label(
                "Pakiet zawiera informacje o środowisku i logi techniczne. "
                "Nie zawiera projektu ani plików GPS. "
                "Logi błędów mogą zawierać lokalne ścieżki plików."
            )
        )
        for mode in ("DAY", "DARK", "AMBER", "RED OPS"):
            button = self.button(layout, mode + " — planowane; obecnie motyw QGIS", lambda: None)
            button.setEnabled(False)
        layout.addStretch()
