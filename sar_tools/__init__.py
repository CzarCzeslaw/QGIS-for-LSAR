"""QGIS SAR Tools. Importing the package does not require QGIS."""

__version__ = "0.1.0"


def classFactory(iface):
    from .plugin import SarToolsPlugin

    return SarToolsPlugin(iface)
