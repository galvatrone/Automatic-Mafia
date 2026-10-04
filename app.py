import multiprocessing as mp

from automatic_mafia.ui.qt_app import run


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    run()
