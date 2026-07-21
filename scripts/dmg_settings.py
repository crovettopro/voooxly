"""Layout of the Voooxly installer window, for dmgbuild.

Invoked from release.sh as:
    dmgbuild -s scripts/dmg_settings.py \
             -D app=<path to Voooxly.app> -D icon=<path to Voooxly.icns> \
             Voooxly out.dmg

Both paths arrive as defines because dmgbuild `exec`s this file without a
`__file__`, so it cannot work out where the repo lives on its own.

No background image on purpose: a PNG cannot follow the system's light/dark
appearance, and a plain window does. The volume icon is what a bare
`hdiutil create` was missing.
"""
import os.path

application = defines["app"]  # noqa: F821 — dmgbuild injects `defines`
appname = os.path.basename(application)

format = "UDZO"
files = [application]
symlinks = {"Applications": "/Applications"}
icon = defines["icon"]  # noqa: F821

window_rect = ((200, 200), (660, 420))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
arrange_by = None
label_pos = "bottom"
text_size = 13
icon_size = 128
icon_locations = {
    appname: (170, 190),
    "Applications": (490, 190),
}
background = None
