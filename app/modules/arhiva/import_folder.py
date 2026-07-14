"""CLI uvoz svih kalkulacija iz foldera.

Pokretanje:  python -m app.modules.arhiva.import_folder "C:\\putanja\\do\\foldera"
"""
import glob
import os
import sys

from app.core.database import Base, SessionLocal, engine
from app.modules.arhiva import models  # noqa: F401 — registrira tablice
from app.modules.arhiva import parser, service


def main(folder: str) -> None:
    Base.metadata.create_all(bind=engine)
    datoteke = sorted(glob.glob(os.path.join(folder, "*.xlsx")))
    if not datoteke:
        print(f"Nema .xlsx datoteka u: {folder}")
        return

    db = SessionLocal()
    novih = preskocenih = gresaka = 0
    try:
        for put in datoteke:
            ime = os.path.basename(put)
            if ime.startswith("~$"):
                continue
            try:
                k = parser.parsiraj(put)
            except Exception as e:
                print(f"[GRESKA]   {ime}: {e}")
                gresaka += 1
                continue
            zapis, novo = service.spremi_kalkulaciju(db, k)
            if novo:
                nap = f"  !! {'; '.join(k.upozorenja)}" if k.upozorenja else ""
                print(f"[NOVO]     {ime}: {k.kupac[:20]:<20} | {k.naziv_proizvoda[:35]:<35} "
                      f"| CK={k.ck_total:>9.2f} EUR | serija={k.serija}{nap}")
                novih += 1
            else:
                print(f"[POSTOJI]  {ime}: kalkulacija {k.broj} vec u bazi — preskacem")
                preskocenih += 1
        db.commit()
    finally:
        db.close()
    print(f"\nUvezeno novih: {novih} | preskoceno: {preskocenih} | greske: {gresaka}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
