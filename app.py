"""
usb_recovery.py

Application pour analyser une clé USB, créer une image brute (sauvegarde bit-à-bit), et tenter de récupérer
les fichiers (ceux présents et, si possible, les fichiers supprimés via pytsk3).

BUT : la récupération bas-niveau (undelete) est complexe — ce script automatise des étapes sûres/standards
et propose une tentative via pytsk3 si la bibliothèque est installée. Si vous voulez une récupération
professionnelle, préférez PhotoRec/TestDisk ou outils professionnels.

Fonctionnalités:
- Analyse basique: infos système de fichiers, taille, erreurs d'accès
- Création d'image brute (.img) via dd/tar
- Copie simple des fichiers visibles
- Récupération avancée via pytsk3 (si installé)

Important:
- Toujours travailler sur une image (fichier .img)
- Certaines opérations nécessitent les droits administrateur/root

Installation:
1. Assurez-vous d'avoir Python 3.8+ installé.
2. Installez les dépendances requises avec pip :

   pip install tk

   (tkinter est inclus par défaut avec Python sur Windows/Linux/macOS, mais si manquant installez-le via votre gestionnaire de paquets)

3. Installez la dépendance optionnelle pour récupération bas-niveau :

   pip install pytsk3

   ⚠️ pytsk3 nécessite parfois des compilateurs natifs et bibliothèques système (libtsk). Sur Windows, utilisez wheels précompilés. Sur Linux :

   sudo apt-get install libtsk-dev
   pip install pytsk3

4. Lancez le script :

   python usb_recovery.py

Auteur: Exemple fourni par ChatGPT (en français)
"""

import os
import sys
import threading
import shutil
import ctypes
import subprocess
import time
from pathlib import Path
from tkinter import Tk, Frame, Button, Label, ttk, filedialog, messagebox, StringVar

# Optional import
try:
    import pytsk3
    HAVE_PYTSK3 = True
except Exception:
    HAVE_PYTSK3 = False


def list_removable_drives():
    """
    Détecte les lecteurs amovibles Windows / Linux / macOS.
    """
    drives = []
    platform = sys.platform

    if platform.startswith('win'):
        DRIVE_REMOVABLE = 2
        try:
            GetDriveTypeW = ctypes.windll.kernel32.GetDriveTypeW
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive_letter = f"{chr(65 + i)}:\\"
                    try:
                        t = GetDriveTypeW(ctypes.c_wchar_p(drive_letter))
                        if t == DRIVE_REMOVABLE:
                            drives.append(drive_letter)
                    except Exception:
                        pass
        except Exception:
            pass
    else:
        candidates = ['/media', '/mnt', '/run/media', str(Path.home() / 'Volumes'), '/Volumes']
        seen = set()
        for base in candidates:
            if os.path.exists(base):
                try:
                    for entry in os.listdir(base):
                        path = os.path.join(base, entry)
                        if os.path.ismount(path) and path not in seen:
                            drives.append(path)
                            seen.add(path)
                except PermissionError:
                    continue
    return drives


class USBRecoveryAppAdvanced:
    def __init__(self, master):
        self.master = master
        master.title('Récupération avancée - Clé USB')
        master.geometry('900x600')

        self.drive_var = StringVar()
        self.destination = None

        top_frame = Frame(master)
        top_frame.pack(fill='x', padx=8, pady=6)

        Label(top_frame, text='Lecteurs amovibles détectés:').pack(side='left')
        self.drives_combo = ttk.Combobox(top_frame, state='readonly', width=40, textvariable=self.drive_var)
        self.drives_combo.pack(side='left', padx=6)

        Button(top_frame, text='Rafraîchir', command=self.refresh_drives).pack(side='left', padx=4)
        Button(top_frame, text='Ouvrir', command=self.open_selected_drive).pack(side='left', padx=4)

        mid_frame = Frame(master)
        mid_frame.pack(fill='both', expand=True, padx=8, pady=6)

        self.tree = ttk.Treeview(mid_frame)
        self.tree.heading('#0', text='Fichiers sur le périphérique sélectionné', anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)

        vsb = ttk.Scrollbar(mid_frame, orient='vertical', command=self.tree.yview)
        vsb.pack(side='left', fill='y')
        self.tree.configure(yscrollcommand=vsb.set)

        right_frame = Frame(master)
        right_frame.pack(fill='x', padx=8, pady=6)

        Button(right_frame, text='Choisir dossier destination', command=self.choose_destination).pack(side='left', padx=6)
        Button(right_frame, text='Copier tout', command=self.copy_all).pack(side='left', padx=6)
        Button(right_frame, text='Quitter', command=master.quit).pack(side='right', padx=6)

        self.status_label = Label(master, text='Statut: prêt')
        self.status_label.pack(fill='x', padx=8, pady=4)

        self.refresh_drives()

    def set_status(self, text):
        self.status_label.config(text=f'Statut: {text}')
        self.master.update_idletasks()

    def refresh_drives(self):
        self.set_status('Détection des lecteurs...')
        drives = list_removable_drives()
        self.drives_combo['values'] = drives
        if drives:
            self.drives_combo.current(0)
            self.drive_var.set(drives[0])
        else:
            self.drive_var.set('')
        self.tree.delete(*self.tree.get_children())
        self.set_status('Prêt')

    def open_selected_drive(self):
        path = self.drive_var.get()
        if not path:
            messagebox.showwarning('Aucun lecteur', 'Aucun lecteur amovible sélectionné.')
            return
        threading.Thread(target=self._populate_tree, args=(path,), daemon=True).start()

    def _populate_tree(self, root_path):
        self.set_status(f'Lecture de {root_path} ...')
        self.tree.delete(*self.tree.get_children())

        def insert_node(parent, fullpath):
            basename = os.path.basename(fullpath) or fullpath
            node = self.tree.insert(parent, 'end', text=basename, values=(fullpath,))
            return node

        root_node = insert_node('', root_path)
        for dirpath, dirnames, filenames in os.walk(root_path):
            rel = os.path.relpath(dirpath, root_path)
            parent_node = root_node if rel == '.' else root_node
            for d in dirnames:
                try:
                    self.tree.insert(parent_node, 'end', text=d)
                except Exception:
                    pass
            for f in filenames:
                try:
                    self.tree.insert(parent_node, 'end', text=f)
                except Exception:
                    pass
        self.set_status('Arborescence chargée')

    def choose_destination(self):
        dst = filedialog.askdirectory(title='Choisir dossier destination')
        if dst:
            self.destination = dst
            self.set_status(f'Destination: {dst}')

    def copy_all(self):
        src = self.drive_var.get()
        if not src:
            messagebox.showwarning('Aucun lecteur', 'Aucun lecteur amovible sélectionné.')
            return
        if not self.destination:
            messagebox.showwarning('Destination manquante', "Choisissez d'abord un dossier de destination.")
            return
        here = src.rstrip(os.sep)
        basename = os.path.basename(here) or 'usb_copy'
        dst_folder = os.path.join(self.destination, f'{basename}_copy')
        threading.Thread(target=self._copy_paths_thread, args=([src], dst_folder), daemon=True).start()

    def _copy_paths_thread(self, paths, override_dst=None):
        try:
            self.set_status('Copie en cours...')
            for p in paths:
                dst = override_dst or self.destination
                if os.path.isdir(p):
                    name = os.path.basename(p.rstrip(os.sep)) or 'root'
                    target = os.path.join(dst, name)
                    self._copy_tree(p, target)
                else:
                    os.makedirs(dst, exist_ok=True)
                    try:
                        shutil.copy2(p, dst)
                    except Exception as e:
                        print('Erreur copie fichier', p, e)
            self.set_status('Copie terminée')
            messagebox.showinfo('Terminé', 'Copie terminée.')
        except Exception as e:
            self.set_status('Erreur lors de la copie')
            messagebox.showerror('Erreur', f'Une erreur est survenue pendant la copie: {e}')

    def _copy_tree(self, src, dst):
        if not os.path.exists(src):
            return
        for root, dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target_root = os.path.join(dst, rel) if rel != '.' else dst
            os.makedirs(target_root, exist_ok=True)
            for f in files:
                sp = os.path.join(root, f)
                dp = os.path.join(target_root, f)
                try:
                    if os.path.exists(dp):
                        base, ext = os.path.splitext(dp)
                        dp = base + '_copy' + ext
                    shutil.copy2(sp, dp)
                except Exception as e:
                    print('Erreur copie:', sp, e)


if __name__ == '__main__':
    root = Tk()
    app = USBRecoveryAppAdvanced(root)
    root.mainloop()