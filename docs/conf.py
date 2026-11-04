"""Sphinx configuration for geoetl's documentation.

Built with Sphinx + MyST (Markdown) + furo, hosted on Read the Docs.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(".."))

import geoetl  # noqa: E402

project = "geoetl"
author = "Heather Baier"
copyright = f"{project} contributors"
release = geoetl.__version__ if hasattr(geoetl, "__version__") else "0.1.0"
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # reads the NumPy-style docstrings already in geoetl/io/*.py
    "sphinx.ext.viewcode",  # adds "view source" links on API reference pages
    "sphinx.ext.intersphinx",
    "myst_parser",  # write pages in Markdown instead of reStructuredText
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- autodoc -----------------------------------------------------------------
autodoc_member_order = "bysource"
autodoc_typehints = "description"
napoleon_google_docstring = False
napoleon_numpy_docstring = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- HTML output ---------------------------------------------------------
# No _static/_templates dirs yet (nothing to put in them); add
# html_static_path/templates_path back once there's custom CSS or a
# template override to ship.
html_theme = "furo"
html_title = "geoetl"
html_theme_options = {
    "source_repository": "https://github.com/heatherbaier/geoetl",
    "source_branch": "master",
    "source_directory": "docs/",
}
