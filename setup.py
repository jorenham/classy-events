from pathlib import Path

from setuptools import find_packages, setup

_BASE_PATH = Path(__file__).parent
_VERSION_PATH = _BASE_PATH / "VERSION"

NAME = "classy-events"
DESCRIPTION = "Pythonic event-driven programming."
with open(_BASE_PATH / "README.md", "r") as f:
    LONG_DESCRIPTION = f.read()

URL = "https://github.com/jorenham/classy-events/"
AUTHOR = "Joren Hammudoglu"

REQUIRES_PYTHON = ">=3.8.0"
VERSION = _VERSION_PATH.read_text().strip()
REQUIREMENTS = ["classy-decorators==1.0.0"]

setup(
    name=NAME,
    description=DESCRIPTION,
    author=AUTHOR,
    url=URL,
    version=VERSION,
    install_requires=REQUIREMENTS,
    python_requires=REQUIRES_PYTHON,
    packages=find_packages(exclude=["tests"]),
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    classifiers=[
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX",
    ],
)
