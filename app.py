import multiprocessing as mp

from automatic_mafia.ui.app import MafiaApp


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    app = MafiaApp()
    app.mainloop()
