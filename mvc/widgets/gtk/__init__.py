import os
import sys
import gtk
import gobject

def initialize(app):
    from gtkmenus import MainWindowMenuBar
    app.menubar = MainWindowMenuBar()
    app.startup()
    app.run()

def attach_menubar():
    from mvc.widgets import app
    app.widgetapp.vbox.pack_start(app.widgetapp.menubar)

def mainloop_start():
    gobject.threads_init()
    gtk.main()

def mainloop_stop():
    gtk.main_quit()

def idle_add(callback, periodic=None):
    if periodic is not None and periodic < 0:
        raise ValueError('periodic cannot be negative')
    def wrapper():
        callback()
        return periodic is not None
    delay = periodic
    if delay is not None:
        delay *= 1000    # milliseconds
    else:
        delay = 0
    return gobject.timeout_add(delay, wrapper)

def idle_remove(id_):
    gobject.source_remove(id_)

def check_kde():
    return os.environ.get("KDE_FULL_SESSION", None) != None

def open_file_linux(filename):
    if check_kde():
        os.spawnlp(os.P_NOWAIT, "kfmclient", "kfmclient",
                   "exec", "file://" + filename)
    else:
        os.spawnlp(os.P_NOWAIT, "gnome-open", "gnome-open", filename)

def reveal_file(filename):
    if hasattr(os, 'startfile'): # Windows
        os.startfile(os.path.dirname(filename))
    else:
        open_file_linux(filename)

def get_conversion_directory_windows():
    from mvc.windows import specialfolders
    return specialfolders.non_video_directory

def get_conversion_directory_linux():
    return os.path.expanduser('~/Desktop')

if sys.platform == 'win32':   
    get_conversion_directory = get_conversion_directory_windows
else:
    get_conversion_directory = get_conversion_directory_linux
