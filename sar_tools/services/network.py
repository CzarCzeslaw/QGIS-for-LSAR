"""Cancelable Qt requests; no address contents are logged or sent while typing."""

import time

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from ..core.errors import SarError
from ..core.geocoding import address_url, parse_results


class AddressSearch(QObject):
    results = pyqtSignal(list)
    failed = pyqtSignal(str, str)
    busy = pyqtSignal(bool)

    def __init__(self, diagnostics, parent=None):
        super().__init__(parent)
        self.diagnostics = diagnostics
        self.reply = None
        self.serial = 0

    def cancel(self):
        self.serial += 1
        if self.reply is not None:
            self.reply.abort()
            self.reply = None
        self.busy.emit(False)

    def search(self, query):
        self.cancel()
        url = address_url(query)
        serial = self.serial
        started = time.monotonic()
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"QGIS-SAR-Tools/0.1 (QGIS desktop plugin)")
        request.setTransferTimeout(15000)
        reply = QgsNetworkAccessManager.instance().get(request)
        self.reply = reply
        timer = QTimer(reply)
        timer.setSingleShot(True)
        timed_out = [False]

        def timeout():
            timed_out[0] = True
            reply.abort()

        timer.timeout.connect(timeout)
        timer.start(20000)

        def complete():
            timer.stop()
            try:
                if serial != self.serial:
                    return
                self.reply = None
                self.busy.emit(False)
                if timed_out[0] or reply.error() != QNetworkReply.NetworkError.NoError:
                    raise SarError(
                        "ADDRESS_NETWORK",
                        "Nie udało się połączyć z usługą adresową. "
                        "Sprawdź internet i spróbuj ponownie.",
                    )
                payload = bytes(reply.readAll())
                if len(payload) > 2_000_000:
                    raise SarError("ADDRESS_FORMAT", "Odpowiedź usługi adresowej jest zbyt duża.")
                self.results.emit(parse_results(payload))
                self.diagnostics.event(
                    "address_search_complete %.2fs" % (time.monotonic() - started)
                )
            except SarError as exc:
                self.diagnostics.event("address_search_failed", exc.code)
                self.failed.emit(exc.code, str(exc))
            except Exception:
                self.diagnostics.exception("ADDRESS_INTERNAL")
                self.failed.emit(
                    "ADDRESS_INTERNAL", "Nie udało się przetworzyć wyników wyszukiwania."
                )
            finally:
                reply.deleteLater()

        reply.finished.connect(complete)
        self.busy.emit(True)
