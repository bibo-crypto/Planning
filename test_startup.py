import traceback
from tkinter import ttk

import main
from gui.gui import ConverterApp


def main() -> None:
    callback_errors = []
    try:
        app = ConverterApp()
        app.report_callback_exception = lambda _type, _value, tb: callback_errors.append(
            "".join(traceback.format_exception(_type, _value, tb))
        )

        def visit_notebooks(parent, visited):
            for child in parent.winfo_children():
                if not isinstance(child, ttk.Notebook) or str(child) in visited:
                    continue
                visited.add(str(child))
                for tab_id in child.tabs():
                    child.select(tab_id)
                    app.update()
                    visit_notebooks(app.nametowidget(tab_id), visited)

        def verify_pages():
            visit_notebooks(app, set())
            required_pages = (
                "_timeline_tab", "_show_orders_tab", "_biglietti_tab", "_kamal_tab",
                "_ordine_med_tab", "_settimana_tab", "_master_data_tab",
            )
            missing = [name for name in required_pages if not getattr(app, name, None)]
            if missing:
                callback_errors.append(f"Pages did not load: {', '.join(missing)}")
            timeline = getattr(app, "_timeline_tab", None)
            if timeline is not None:
                app.update_idletasks()
                machine_width = timeline._main.winfo_rootx() - timeline._labels.winfo_rootx()
                if abs(machine_width - timeline.LABEL_W) > 10:
                    callback_errors.append(f"Machine column width is {machine_width}, expected {timeline.LABEL_W}")
                controls_right = timeline._controls.winfo_rootx() + timeline._controls.winfo_width()
                window_right = app.winfo_rootx() + app.winfo_width()
                if controls_right > window_right:
                    callback_errors.append("Machine Timeline toolbar exceeds the application window")
            app.destroy()

        app.after(500, verify_pages)
        app.mainloop()
    except Exception:
        traceback.print_exc()
        raise
    if callback_errors:
        raise RuntimeError("GUI smoke test failures:\n" + "\n".join(callback_errors))
    print("startup_smoke=ok; lazy_pages=ok")


if __name__ == "__main__":
    main()
