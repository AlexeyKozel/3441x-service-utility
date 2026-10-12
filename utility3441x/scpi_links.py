"""Explicit offline navigation links; these do not imply command execution."""

# The checked CAL scalar and bulk transfer handlers access working CAL.
# Saving to NOR is a separate documented command, outside this catalogue.
COMMAND_TOPICS = {
    '0x00768614-set': ('storage',),
    '0x00768614-query': ('storage',),
    '0x007685bc-set': ('storage',),
    '0x007685bc-query': ('storage',),
}


def topics_for_command(row):
    return list(COMMAND_TOPICS.get(row['id'], ()))


def topic_title(topic):
    from .cal_guide import PAGES
    return PAGES[topic][0]


def open_topic(parent, topic):
    """Open a general reference page without requiring a CAL file."""
    import tkinter as tk
    from .cal_guide import CalGuide
    window = tk.Toplevel(parent)
    window.title('Calibration reference')
    window.geometry('1000x720')
    guide = CalGuide(window, [], [], lambda index: None)
    guide.pack(fill='both', expand=True)
    guide.show(topic)
    return window


def open_commands(parent, topic):
    import tkinter as tk
    from .scpi_reference import build_reference_tab
    window = tk.Toplevel(parent)
    window.title('Hidden SCPI reference')
    window.geometry('1080x780')
    view = build_reference_tab(window, navigate_topic=lambda key: open_topic(window, key))
    view.pack(fill='both', expand=True)
    # This bounded link currently covers the working/saved CAL transfer topic.
    if topic == 'storage':
        view.search.set('CAL:DATA')
    return window
