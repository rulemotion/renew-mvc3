"""setup-windows.py -- setup script for windows

Usage:

"""
from distutils import log
from distutils.core import Command, setup
from glob import glob
import itertools
import os
import subprocess
import sys

import py2exe

from mvc import resources

env_path = os.path.abspath(os.path.dirname(os.path.dirname(sys.executable)))
nsis_path = os.path.join(env_path, 'nsis-2.46', 'makensis.exe')

packages = [
    'mvc',
    'mvc.widgets',
    'mvc.widgets.gtk',
    'mvc.ui',
    'mvc.resources',
]

def resources_dir():
    return os.path.dirname(resources.__file__)

def resource_data_files(subdir, globspec='*.*'):
    dest_dir = os.path.join("resources", subdir)
    dir_contents = glob(os.path.join(resources_dir(), subdir, globspec))
    return [(dest_dir, dir_contents)]

def data_files():
    return list(itertools.chain(
        resource_data_files("images"),
        resource_data_files("converters", "*.py"),
    ))

def gtk_includes():
    return ['gtk', 'gobject', 'atk', 'pango', 'pangocairo', 'gio']

def py2exe_includes():
    return gtk_includes()

class bdist_nsis(Command):
    description = "create MVC installer using NSIS"
    user_options = [
    ]

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.run_command('py2exe')
        self.dist_dir = self.get_finalized_command('py2exe').dist_dir

        log.info("building installer")

        nsis_source = os.path.join(os.path.dirname(__file__), 'mvc.nsi')
        self.copy_file(nsis_source, self.dist_dir)
        scrip_path = os.path.join(self.dist_dir, 'mvc.nsi')

        if subprocess.call([nsis_path, scrip_path]) != 0:
            print "ERROR creating the 1 stage installer, quitting"
            return

setup(
    name="Miro Video Converter",
    packages=packages,
    version='3.0',
    windows=[
        {'script': 'mvc/__main__.py',
        'dest_base': 'mvc',
        },
    ],
    data_files=data_files(),
    cmdclass={
        'bdist_nsis': bdist_nsis,
        },
    options={
        'py2exe': {
            'includes': py2exe_includes(),
        },
    },
)
