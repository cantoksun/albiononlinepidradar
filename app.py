# -*- coding: utf-8 -*-
"""
Albion Online Sesli Erken Uyari Radari
(Harici DSP Ses Tanima & HUD Yon Sistemi - Config Tabanli Frekans ve Ses Imzasi Motoru)
"""

import sys
import os
import time
import json
import threading
import wave
import numpy as np
from scipy import signal
import soundcard as sc
import tkinter as tk
from tkinter import ttk, messagebox
from pynput import mouse, keyboard

dizin = os.path.dirname(os.path.abspath(__file__))
config_dosyasi = os.path.join(dizin, "radar_config.json")
veritabani_dosyasi = os.path.join(dizin, "spell_audio_events.json")


class SesliUyariAraci:
    def __init__(self, pencere):
        self.pencere = pencere
        self.pencere.title("albion ses radari - harici ses tanima")
        self.pencere.geometry("540x620")
        self.pencere.resizable(True, True)

        self.calisiyor = False
        self.ses_isparcacigi = None
        self.albion_pid = None
        self.albion_ses_oturumu = None
        self.sablonlar = {}
        self.son_hareket_zamani = 0.0

        # HUD Degiskenleri
        self.hud_pencere = None
        self.hud_canvas = None
        self.hud_ogeler = []
        self.surukleme_baslangic_x = 0
        self.surukleme_baslangic_y = 0

        self.veritabani_yukle()
        self.config_yukle()
        self.sablonlari_yukle()
        self.arayuz_hazirla()
        self.hud_olustur()

        threading.Thread(target=self.albion_baglan, daemon=True).start()
        threading.Thread(target=self.hareket_dinleyici, daemon=True).start()

    def veritabani_yukle(self):
        self.ses_veritabani = {}
        if os.path.exists(veritabani_dosyasi):
            try:
                with open(veritabani_dosyasi, "r", encoding="utf-8") as f:
                    self.ses_veritabani = json.load(f)
            except Exception as e:
                print(f"veritabani okuma hatasi: {e}")

    def config_yukle(self):
        if os.path.exists(config_dosyasi):
            try:
                with open(config_dosyasi, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception:
                self.config = {}
        else:
            self.config = {}

        if "ayarlar" not in self.config:
            self.config["ayarlar"] = {
                "ornekleme_hizi": 16000,
                "pencere_suresi_sn": 1.2,
                "adim_suresi_sn": 0.08,
                "tekrar_uyari_bekleme_sn": 1.4,
                "albion_ses_esigi": 0.0003,
                "hareket_susturma_suresi_sn": 1.3,
                "discord_izolasyonu_aktif": True,
                "hareket_susturma_aktif": True,
                "kulaklik_bip_aktif": True,
                "ekran_flasi_aktif": True,
                "hud_aktif": True,
                "hud_x": 40,
                "hud_y": 60,
            }

        if "izlenecek_sesler" not in self.config:
            self.config["izlenecek_sesler"] = []

    def config_kaydet(self):
        try:
            with open(config_dosyasi, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"config kaydetme hatasi: {e}")

    def sablonlari_yukle(self):
        hedef_sr = self.config.get("ayarlar", {}).get("ornekleme_hizi", 16000)
        self.sablonlar.clear()

        for item in self.config.get("izlenecek_sesler", []):
            if item.get("tur") != "sablon":
                continue
            sablon_id = item.get("id")
            dosya_adi = item.get("sablon_dosyasi")
            if not dosya_adi:
                continue
            yol = os.path.join(dizin, dosya_adi)

            if os.path.exists(yol):
                try:
                    with wave.open(yol, "rb") as wf:
                        orig_sr = wf.getframerate()
                        raw = wf.readframes(wf.getnframes())
                        tam_ses = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                        if orig_sr != hedef_sr:
                            hedef_len = int(len(tam_ses) * hedef_sr / orig_sr)
                            tam_ses = signal.resample(tam_ses, hedef_len)

                        basla = int(item.get("baslangic_sn", 0.0) * hedef_sr)
                        sure = int(item.get("sure_sn", 0.35) * hedef_sr)
                        bitir = basla + sure
                        kirpik = tam_ses[basla:bitir] if (bitir <= len(tam_ses) and sure > 0) else tam_ses

                        norm = np.linalg.norm(kirpik)
                        if norm > 1e-4:
                            self.sablonlar[sablon_id] = {
                                "ses": kirpik,
                                "norm": norm,
                                "ones": np.ones(len(kirpik), dtype=np.float32),
                                "cfg": item,
                            }
                except Exception as e:
                    print(f"sablon yukleme hatasi ({dosya_adi}): {e}")

    def albion_baglan(self):
        while True:
            try:
                from pycaw.pycaw import AudioUtilities
                oturumlar = AudioUtilities.GetAllSessions()
                bulundu = False
                for oturum in oturumlar:
                    if oturum.Process and "albion" in oturum.Process.name().lower():
                        self.albion_pid = oturum.ProcessId
                        self.albion_ses_oturumu = oturum
                        bulundu = True
                        break

                if bulundu:
                    self.lbl_baglanti.config(text=f"albion bagli (pid: {self.albion_pid})", foreground="#2e7d32")
                else:
                    self.lbl_baglanti.config(text="albion bekleniyor...", foreground="#d32f2f")
            except Exception:
                pass
            time.sleep(3)

    def hareket_dinleyici(self):
        def tus_basildi(tus):
            try:
                if hasattr(tus, "char") and tus.char and tus.char.lower() in ["w", "a", "s", "d", "q", "e", "r", "f"]:
                    self.son_hareket_zamani = time.time()
                elif tus in [keyboard.Key.space, keyboard.Key.shift, keyboard.Key.ctrl]:
                    self.son_hareket_zamani = time.time()
            except Exception:
                pass

        def tiklandi(x, y, button, pressed):
            if pressed and button == mouse.Button.right:
                self.son_hareket_zamani = time.time()

        klavye_dinleyici = keyboard.Listener(on_press=tus_basildi)
        fare_dinleyici = mouse.Listener(on_click=tiklandi)
        klavye_dinleyici.daemon = True
        fare_dinleyici.daemon = True
        klavye_dinleyici.start()
        fare_dinleyici.start()

    def hud_olustur(self):
        hud_ayarlar = self.config.get("ayarlar", {})
        baslangic_x = hud_ayarlar.get("hud_x", 40)
        baslangic_y = hud_ayarlar.get("hud_y", 60)

        self.hud_pencere = tk.Toplevel(self.pencere)
        self.hud_pencere.title("albion_hud")
        self.hud_pencere.geometry(f"360x105+{baslangic_x}+{baslangic_y}")
        self.hud_pencere.overrideredirect(True)
        self.hud_pencere.attributes("-topmost", True)
        self.hud_pencere.attributes("-alpha", 0.95)

        arkaplan_renk = "#010203"
        self.hud_pencere.configure(bg=arkaplan_renk)
        self.hud_pencere.wm_attributes("-transparentcolor", arkaplan_renk)

        self.hud_canvas = tk.Canvas(self.hud_pencere, bg=arkaplan_renk, highlightthickness=0, bd=0)
        self.hud_canvas.pack(fill=tk.BOTH, expand=True)

        self.hud_canvas.bind("<Button-1>", self.hud_surukle_basla)
        self.hud_canvas.bind("<B1-Motion>", self.hud_surukle_devam)

        if not hud_ayarlar.get("hud_aktif", True):
            self.hud_pencere.withdraw()

        self.hud_ciz_varsayilan()

    def hud_ciz_vektor_ok(self, cx, cy, dir_kod, renk, r=7):
        aci_haritasi = {
            "N": -90,
            "NE": -45,
            "E": 0,
            "SE": 45,
            "S": 90,
            "SW": 135,
            "W": 180,
            "NW": -135,
        }
        deg = aci_haritasi.get(dir_kod, -90)
        rad = np.radians(deg)

        uc_x = cx + r * np.cos(rad)
        uc_y = cy + r * np.sin(rad)
        kuyruk_x = cx - r * np.cos(rad)
        kuyruk_y = cy - r * np.sin(rad)

        kanat_aci1 = rad + np.radians(145)
        kanat_aci2 = rad - np.radians(145)
        kanat_len = r * 0.75

        k1_x = uc_x + kanat_len * np.cos(kanat_aci1)
        k1_y = uc_y + kanat_len * np.sin(kanat_aci1)
        k2_x = uc_x + kanat_len * np.cos(kanat_aci2)
        k2_y = uc_y + kanat_len * np.sin(kanat_aci2)

        self.hud_canvas.create_line(kuyruk_x, kuyruk_y, uc_x, uc_y, fill=renk, width=2, capstyle=tk.ROUND)
        self.hud_canvas.create_line(uc_x, uc_y, k1_x, k1_y, fill=renk, width=2, capstyle=tk.ROUND)
        self.hud_canvas.create_line(uc_x, uc_y, k2_x, k2_y, fill=renk, width=2, capstyle=tk.ROUND)

    def hud_ciz_varsayilan(self):
        self.hud_canvas.delete("all")
        self.hud_ciz_vektor_ok(14, 18, "N", "#888888", r=6)
        self.hud_canvas.create_text(
            28, 18,
            text="albion ses radari devrede",
            anchor=tk.W,
            fill="#888888",
            font=("Segoe UI", 10, "bold")
        )

    def hud_surukle_basla(self, event):
        self.surukleme_baslangic_x = event.x
        self.surukleme_baslangic_y = event.y

    def hud_surukle_devam(self, event):
        dx = event.x - self.surukleme_baslangic_x
        dy = event.y - self.surukleme_baslangic_y
        yeni_x = self.hud_pencere.winfo_x() + dx
        yeni_y = self.hud_pencere.winfo_y() + dy
        self.hud_pencere.geometry(f"+{yeni_x}+{yeni_y}")
        self.config["ayarlar"]["hud_x"] = yeni_x
        self.config["ayarlar"]["hud_y"] = yeni_y

    def hud_gecis(self):
        if self.var_hud.get():
            self.hud_pencere.deiconify()
        else:
            self.hud_pencere.withdraw()

    def hud_guncelle(self):
        if not self.hud_canvas:
            return
        self.hud_canvas.delete("all")

        if not self.hud_ogeler:
            self.hud_ciz_varsayilan()
            return

        satir_y = [18, 48, 78]
        for idx, item in enumerate(self.hud_ogeler[-3:]):
            y = satir_y[idx]
            dir_kod = item.get("dir_kod", "N")
            metin = item.get("metin", "")

            # Temiz saf beyaz metin ve net vektor ok
            self.hud_ciz_vektor_ok(14, y, dir_kod, "#ffffff", r=7)
            self.hud_canvas.create_text(
                30, y,
                text=metin,
                anchor=tk.W,
                fill="#ffffff",
                font=("Segoe UI", 10, "bold")
            )

    def arayuz_hazirla(self):
        ana = ttk.Frame(self.pencere, padding=10)
        ana.pack(fill=tk.BOTH, expand=True)

        grup_durum = ttk.LabelFrame(ana, text="durum & oyun sesi izolasyonu", padding=8)
        grup_durum.pack(fill=tk.X, pady=4)

        self.lbl_baglanti = ttk.Label(grup_durum, text="albion araniyor...", font=("Segoe UI", 9, "bold"))
        self.lbl_baglanti.pack(side=tk.LEFT)

        self.bar_ses = ttk.Progressbar(grup_durum, length=160, mode="determinate")
        self.bar_ses.pack(side=tk.RIGHT, padx=4)
        ttk.Label(grup_durum, text="albion ses seviyesi:").pack(side=tk.RIGHT)

        # Config tabanli izlenecek sesler cercevesi
        grup_ayar = ttk.LabelFrame(ana, text="radarda izlenen sesler & frekans profilleri", padding=6)
        grup_ayar.pack(fill=tk.BOTH, expand=True, pady=4)

        canvas_kapsayici = tk.Canvas(grup_ayar, highlightthickness=0, height=220)
        kaydirma = ttk.Scrollbar(grup_ayar, orient="vertical", command=canvas_kapsayici.yview)
        self.kaydirilabilir_cerceve = ttk.Frame(canvas_kapsayici)

        self.kaydirilabilir_cerceve.bind(
            "<Configure>",
            lambda e: canvas_kapsayici.configure(scrollregion=canvas_kapsayici.bbox("all"))
        )
        canvas_kapsayici.create_window((0, 0), window=self.kaydirilabilir_cerceve, anchor="nw")
        canvas_kapsayici.configure(yscrollcommand=kaydirma.set)

        canvas_kapsayici.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")

        self.ui_ses_ogeleri = {}
        for item in self.config.get("izlenecek_sesler", []):
            sid = item.get("id")
            var_aktif = tk.BooleanVar(value=item.get("aktif", True))

            f_aralik = item.get("frekans_araligi_hz")
            f_bilgi = f" [{f_aralik[0]}-{f_aralik[1]} hz]" if f_aralik else " [sablon]"
            cb_text = item.get("etiket", sid) + f_bilgi

            cb = ttk.Checkbutton(self.kaydirilabilir_cerceve, text=cb_text, variable=var_aktif)
            cb.pack(anchor=tk.W, pady=1)

            satir = ttk.Frame(self.kaydirilabilir_cerceve)
            satir.pack(fill=tk.X, padx=12, pady=1)
            ttk.Label(satir, text="hassasiyet:").pack(side=tk.LEFT)

            slider = ttk.Scale(satir, from_=20, to=85, value=item.get("hassasiyet", 45))
            slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

            lbl_deger = ttk.Label(satir, text=f"%{int(slider.get())}", width=5)
            lbl_deger.pack(side=tk.RIGHT)

            def guncelle(val, l=lbl_deger):
                l.config(text=f"%{int(float(val))}")
            slider.config(command=guncelle)

            self.ui_ses_ogeleri[sid] = {
                "var": var_aktif,
                "slider": slider,
                "lbl": lbl_deger,
                "cfg": item,
            }

        ayarlar = self.config.get("ayarlar", {})
        grup_ek = ttk.Frame(ana)
        grup_ek.pack(fill=tk.X, pady=2)

        self.var_izole = tk.BooleanVar(value=ayarlar.get("discord_izolasyonu_aktif", True))
        ttk.Checkbutton(grup_ek, text="sadece albion ses urettiginde dinle (discord/muzik engellenir)", variable=self.var_izole).pack(anchor=tk.W, pady=1)

        self.var_hareket = tk.BooleanVar(value=ayarlar.get("hareket_susturma_aktif", True))
        ttk.Checkbutton(grup_ek, text="sen hareket halindeyken (kosarken) alarmi sustur", variable=self.var_hareket).pack(anchor=tk.W, pady=1)

        grup_uyari = ttk.LabelFrame(ana, text="uyari sekli & ekran ustu temiz beyaz metin", padding=8)
        grup_uyari.pack(fill=tk.X, pady=4)

        self.var_hud = tk.BooleanVar(value=ayarlar.get("hud_aktif", True))
        ttk.Checkbutton(grup_uyari, text="ekranda son 3 sesi goster (temiz beyaz)", variable=self.var_hud, command=self.hud_gecis).pack(side=tk.LEFT, padx=4)

        self.var_sesli = tk.BooleanVar(value=ayarlar.get("kulaklik_bip_aktif", True))
        ttk.Checkbutton(grup_uyari, text="bip sesi", variable=self.var_sesli).pack(side=tk.LEFT, padx=4)

        self.var_gorsel = tk.BooleanVar(value=ayarlar.get("ekran_flasi_aktif", True))
        ttk.Checkbutton(grup_uyari, text="kirmizi flas", variable=self.var_gorsel).pack(side=tk.LEFT, padx=4)

        ttk.Button(grup_uyari, text="ayarlari kaydet", command=self.arayuzden_kaydet).pack(side=tk.RIGHT, padx=4)
        ttk.Button(grup_uyari, text="test et", width=8, command=self.test_uyari).pack(side=tk.RIGHT, padx=4)

        alt_kutu = ttk.Frame(ana, padding=4)
        alt_kutu.pack(fill=tk.X, pady=4)

        self.btn_baslat = ttk.Button(alt_kutu, text="izlemeyi baslat", command=self.baslat)
        self.btn_baslat.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        self.btn_durdur = ttk.Button(alt_kutu, text="durdur", command=self.durdur, state=tk.DISABLED)
        self.btn_durdur.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        grup_log = ttk.LabelFrame(ana, text="algilama gunlugu (oyun ses olaylari)", padding=4)
        grup_log.pack(fill=tk.BOTH, expand=True, pady=2)

        self.yazi_alani = tk.Text(grup_log, height=5, relief="solid", bd=1, font=("Consolas", 9))
        self.yazi_alani.pack(fill=tk.BOTH, expand=True)

        self.yaz(f"veritabani ve config hazir ({len(self.config.get('izlenecek_sesler', []))} ses profili tanimli).")

    def arayuzden_kaydet(self):
        for item in self.config.get("izlenecek_sesler", []):
            sid = item.get("id")
            if sid in self.ui_ses_ogeleri:
                item["aktif"] = bool(self.ui_ses_ogeleri[sid]["var"].get())
                item["hassasiyet"] = int(self.ui_ses_ogeleri[sid]["slider"].get())

        self.config["ayarlar"]["discord_izolasyonu_aktif"] = bool(self.var_izole.get())
        self.config["ayarlar"]["hareket_susturma_aktif"] = bool(self.var_hareket.get())
        self.config["ayarlar"]["kulaklik_bip_aktif"] = bool(self.var_sesli.get())
        self.config["ayarlar"]["ekran_flasi_aktif"] = bool(self.var_gorsel.get())
        self.config["ayarlar"]["hud_aktif"] = bool(self.var_hud.get())

        self.config_kaydet()
        self.sablonlari_yukle()
        self.yaz("guncel ayarlar radar_config.json dosyasina kaydedildi.")

    def yaz(self, metin):
        zaman_damgasi = time.strftime("%H:%M:%S")
        self.yazi_alani.insert(tk.END, f"[{zaman_damgasi}] {metin}\n")
        self.yazi_alani.see(tk.END)

    def test_uyari(self):
        self.uyari_ver("test uyarisi", "ses radari calisiyor", ("NW", "north-west [kuzeybati]"))

    def uyari_ver(self, yetenek_turu, detay_metni, yon_bilgisi=("N", "north [kuzey]")):
        dir_kod, yon_aciklama = yon_bilgisi
        self.yaz(f"[YON: {yon_aciklama}] {yetenek_turu} -> {detay_metni}")

        hud_metin = f"{yetenek_turu} - {yon_aciklama.split('[')[0].strip().upper()}"
        self.hud_ogeler.append({"dir_kod": dir_kod, "metin": hud_metin, "zaman": time.time()})
        if len(self.hud_ogeler) > 3:
            self.hud_ogeler.pop(0)

        self.hud_guncelle()

        if self.var_gorsel.get():
            threading.Thread(target=self.ekran_flasi, daemon=True).start()

        if self.var_sesli.get():
            try:
                import winsound
                winsound.Beep(950, 100)
            except Exception:
                pass

    def ekran_flasi(self):
        try:
            flas = tk.Toplevel(self.pencere)
            flas.overrideredirect(True)
            flas.attributes("-topmost", True)
            flas.attributes("-alpha", 0.22)
            flas.geometry(f"{self.pencere.winfo_screenwidth()}x{self.pencere.winfo_screenheight()}+0+0")
            flas.configure(bg="#ff2222")
            self.pencere.after(120, flas.destroy)
        except Exception:
            pass

    def baslat(self):
        if self.calisiyor:
            return
        self.calisiyor = True
        self.btn_baslat.config(state=tk.DISABLED)
        self.btn_durdur.config(state=tk.NORMAL)
        self.yaz("ses izleme motoru baslatildi.")

        self.ses_isparcacigi = threading.Thread(target=self.ses_dongusu, daemon=True)
        self.ses_isparcacigi.start()

    def durdur(self):
        self.calisiyor = False
        self.btn_baslat.config(state=tk.NORMAL)
        self.btn_durdur.config(state=tk.DISABLED)
        self.yaz("ses izleme durduruldu.")

    def ses_yonu_hesapla(self, sol_kanal, sag_kanal):
        rms_sol = np.sqrt(np.mean(sol_kanal**2)) + 1e-8
        rms_sag = np.sqrt(np.mean(sag_kanal**2)) + 1e-8

        oran = (rms_sag - rms_sol) / (rms_sag + rms_sol)

        if oran > 0.40:
            return ("E", "east [dogu]")
        elif oran < -0.40:
            return ("W", "west [bati]")
        elif 0.15 < oran <= 0.40:
            return ("NE", "north-east [kuzeydogu]")
        elif -0.40 <= oran < -0.15:
            return ("NW", "north-west [kuzeybati]")
        else:
            return ("N", "north [kuzey]")

    def ses_dongusu(self):
        ayarlar = self.config.get("ayarlar", {})
        ornekleme = ayarlar.get("ornekleme_hizi", 16000)
        pencere_sn = ayarlar.get("pencere_suresi_sn", 1.2)
        adim_sn = ayarlar.get("adim_suresi_sn", 0.08)
        bekleme_sn = ayarlar.get("tekrar_uyari_bekleme_sn", 1.4)
        albion_esik = ayarlar.get("albion_ses_esigi", 0.0003)
        hareket_susturma_sn = ayarlar.get("hareket_susturma_suresi_sn", 1.3)

        pencere_boyutu = int(ornekleme * pencere_sn)
        adim = int(ornekleme * adim_sn)

        tampon_sol = np.zeros(pencere_boyutu, dtype=np.float32)
        tampon_sag = np.zeros(pencere_boyutu, dtype=np.float32)

        son_uyari_zamani = 0.0
        gecmis_enerjiler = []

        hoparlor = sc.default_speaker()
        if not hoparlor:
            self.yaz("hata: ses cikis cihazi bulunamadi!")
            self.pencere.after(0, self.durdur)
            return

        with sc.get_microphone(id=str(hoparlor.id), include_loopback=True).recorder(samplerate=ornekleme) as kaydedici:
            while self.calisiyor:
                try:
                    if self.var_izole.get() and self.albion_ses_oturumu:
                        albion_peak = 0.0
                        vol_oran = 1.0
                        try:
                            sayac = self.albion_ses_oturumu._ctl.QueryInterface(
                                sys.modules["pycaw.pycaw"].IAudioMeterInformation
                            )
                            albion_peak = sayac.GetPeakValue()

                            vol_ctrl = self.albion_ses_oturumu._ctl.QueryInterface(
                                sys.modules["pycaw.pycaw"].ISimpleAudioVolume
                            )
                            proc_vol = vol_ctrl.GetMasterVolume()
                            vol_oran = max(0.05, float(proc_vol))
                        except Exception:
                            if self.albion_pid:
                                albion_peak = 0.01
                                vol_oran = 1.0

                        dinamik_esik = max(0.0001, albion_esik * vol_oran)
                        gosterge = min(100, int((albion_peak / vol_oran) * 100))
                        self.pencere.after(0, lambda v=gosterge: self.bar_ses.configure(value=v))

                        if albion_peak < dinamik_esik:
                            kaydedici.record(numframes=adim)
                            time.sleep(0.04)
                            continue

                    yeni_veri = kaydedici.record(numframes=adim)
                    if len(yeni_veri) == 0:
                        continue

                    if yeni_veri.ndim > 1 and yeni_veri.shape[1] >= 2:
                        yeni_sol = yeni_veri[:, 0]
                        yeni_sag = yeni_veri[:, 1]
                    else:
                        yeni_sol = yeni_veri.flatten()
                        yeni_sag = yeni_sol

                    tampon_sol[:-adim] = tampon_sol[adim:]
                    tampon_sol[-adim:] = yeni_sol

                    tampon_sag[:-adim] = tampon_sag[adim:]
                    tampon_sag[-adim:] = yeni_sag

                    tampon_mono = 0.5 * (tampon_sol + tampon_sag)

                    genlik = np.max(np.abs(tampon_mono))
                    if genlik < 0.0001:
                        continue

                    simdi = time.time()
                    if self.var_hareket.get() and (simdi - self.son_hareket_zamani < hareket_susturma_sn):
                        continue

                    if simdi - son_uyari_zamani < bekleme_sn:
                        continue

                    aktif_yon = self.ses_yonu_hesapla(tampon_sol[-adim:], tampon_sag[-adim:])

                    # =========================================================================
                    # CONFIG TABANLI SES ESLESTIRME MOTORU (3 ONCELIK KADEMESI)
                    # =========================================================================
                    izlenecek = [s for s in self.config.get("izlenecek_sesler", []) if s.get("aktif", True)]

                    # -------------------------------------------------------------------------
                    # KADEME 1: GERCEK OYUN SES SABLONLARI ILE CARPMA KORELASYONU
                    # (invisibility, dash, chain vb.)
                    # -------------------------------------------------------------------------
                    sablon_bulundu = False
                    for s_cfg in izlenecek:
                        if s_cfg.get("tur") != "sablon":
                            continue
                        sid = s_cfg.get("id")
                        if sid not in self.sablonlar:
                            continue

                        tpl = self.sablonlar[sid]
                        corr = signal.correlate(tampon_mono, tpl["ses"], mode="valid")
                        local_energy = signal.convolve(tampon_mono**2, tpl["ones"], mode="valid")
                        local_norm = np.sqrt(np.maximum(local_energy, 1e-8))
                        skor = float(np.max(corr / (local_norm * tpl["norm"])))

                        ui_ayar = self.ui_ses_ogeleri.get(sid)
                        hedef_esik = (ui_ayar["slider"].get() / 100.0) if ui_ayar else (s_cfg.get("hassasiyet", 35) / 100.0)

                        if skor >= hedef_esik:
                            son_uyari_zamani = simdi
                            sablon_bulundu = True
                            yetenek_adi = s_cfg.get("etiket", sid)
                            yuzde = int(skor * 100)
                            self.pencere.after(0, lambda y=yetenek_adi, p=yuzde, d=aktif_yon: self.uyari_ver(y, f"tespit edildi! (%{p})", d))
                            break

                    if sablon_bulundu:
                        continue

                    # -------------------------------------------------------------------------
                    # KADEME 2: BINEK RITMIK ADIM MOTORU (CONFIG PROFILLERI)
                    # Silahlardan ve asalardan once kontrol edilir; binek seslerinin
                    # quarterstaff veya diger silahlara dusmesini %100 engeller!
                    # -------------------------------------------------------------------------
                    ritmik_binek_bulundu = False
                    ritmik_profiller = [s for s in izlenecek if s.get("tur") == "ritmik_adim"]

                    if ritmik_profiller:
                        sub_len = int(ornekleme * 0.04) # 40ms pencereler
                        alt_enerjiler = [np.sum(tampon_mono[i:i+sub_len]**2) for i in range(0, len(tampon_mono)-sub_len, sub_len//2)]
                        ort_e = np.mean(alt_enerjiler) + 1e-8
                        darbeler = [idx for idx in range(1, len(alt_enerjiler)-1)
                                    if alt_enerjiler[idx] > alt_enerjiler[idx-1]
                                    and alt_enerjiler[idx] > alt_enerjiler[idx+1]
                                    and alt_enerjiler[idx] > ort_e * 1.5]

                        if len(darbeler) >= 3:
                            araliklar = [(darbeler[k+1] - darbeler[k]) * 20 for k in range(len(darbeler)-1)]

                            # Spektrum hesapla
                            fft_binek = np.abs(np.fft.rfft(tampon_mono[-adim:]))
                            f_binek = np.fft.rfftfreq(adim, 1.0 / ornekleme)

                            e_bass = np.sum(fft_binek[(f_binek >= 40) & (f_binek < 300)]**2)
                            e_mid = np.sum(fft_binek[(f_binek >= 300) & (f_binek < 1800)]**2)
                            e_high = np.sum(fft_binek[(f_binek >= 1800) & (f_binek < 4500)]**2)
                            tot_b = e_bass + e_mid + e_high + 1e-8

                            oran_bass = e_bass / tot_b
                            oran_mid = e_mid / tot_b
                            oran_high = e_high / tot_b

                            # Config'deki ritmik binek profilleriyle eslestir
                            for b_cfg in ritmik_profiller:
                                min_int, max_int = b_cfg.get("darbe_araligi_ms", [70, 360])
                                uygun_aralik = sum(1 for a in araliklar if min_int <= a <= max_int)

                                if uygun_aralik >= 2:
                                    odak = b_cfg.get("spektral_odak", "")
                                    eslesti = False
                                    if odak == "high" and oran_high > 0.35:
                                        eslesti = True
                                    elif odak == "mid" and (oran_mid > 0.40):
                                        eslesti = True
                                    elif odak == "bass" and oran_bass > 0.50:
                                        eslesti = True
                                    elif odak == "step":
                                        if (oran_mid + oran_high) > 0.45:
                                            eslesti = True
                                    elif not odak:
                                        eslesti = True

                                    if eslesti:
                                        son_uyari_zamani = simdi
                                        ritmik_binek_bulundu = True
                                        etiket = b_cfg.get("etiket", "yaklasan ritmik ses")
                                        detay = "yaklasan kosan oyuncu ayak sesleri!" if odak == "step" else "yaklasan kosan binek!"
                                        self.pencere.after(0, lambda n=etiket, u=detay, d=aktif_yon: self.uyari_ver(n, u, d))
                                        break

                    if ritmik_binek_bulundu:
                        continue

                    # -------------------------------------------------------------------------
                    # KADEME 3: ANLIK ENERJI PATLAMASI (ASALAR & YAKIN DOVUS SILAHLARI)
                    # -------------------------------------------------------------------------
                    anlik_parca = tampon_mono[-adim:]
                    anlik_enerji = np.sum(anlik_parca**2)
                    gecmis_enerjiler.append(anlik_enerji)
                    if len(gecmis_enerjiler) > 10:
                        gecmis_enerjiler.pop(0)

                    if len(gecmis_enerjiler) >= 5:
                        ort_enerji = np.mean(gecmis_enerjiler[:-1]) + 1e-7
                        artis_orani = anlik_enerji / ort_enerji

                        if artis_orani >= 1.8:
                            fft = np.abs(np.fft.rfft(anlik_parca))
                            freqs = np.fft.rfftfreq(len(anlik_parca), 1.0 / ornekleme)
                            toplam_enerji = np.sum(fft**2) + 1e-8

                            # Config'deki frekans_patlamasi ve ani_darbe profillerini tara
                            eslesen_profil = None
                            for p_cfg in izlenecek:
                                tur = p_cfg.get("tur")
                                if tur not in ["frekans_patlamasi", "ani_darbe"]:
                                    continue

                                f_min, f_max = p_cfg.get("frekans_araligi_hz", [0, 8000])
                                mask = (freqs >= f_min) & (freqs < f_max)
                                bant_enerji = np.sum(fft[mask]**2)
                                oran = bant_enerji / toplam_enerji

                                min_oran = p_cfg.get("min_oran", 0.40)
                                max_high_oran = p_cfg.get("max_yuksek_frekans_orani", 1.0)

                                if oran >= min_oran:
                                    if max_high_oran < 1.0:
                                        yuksek_e = np.sum(fft[freqs >= 2200]**2) / toplam_enerji
                                        if yuksek_e > max_high_oran:
                                            continue

                                    ui_ayar = self.ui_ses_ogeleri.get(p_cfg.get("id"))
                                    kat_hassasiyet = ui_ayar["slider"].get() if ui_ayar else p_cfg.get("hassasiyet", 50)
                                    gereken_artis = max(1.5, 3.8 - (kat_hassasiyet / 35.0))

                                    if artis_orani >= gereken_artis:
                                        eslesen_profil = p_cfg
                                        break

                            if eslesen_profil:
                                son_uyari_zamani = simdi
                                etiket = eslesen_profil.get("etiket", eslesen_profil.get("id"))
                                self.pencere.after(0, lambda e=etiket, r=artis_orani, d=aktif_yon: self.uyari_ver(e, f"saldiri sesi! (guc: {r:.1f}x)", d))
                                continue

                except Exception:
                    time.sleep(0.04)

        self.pencere.after(0, self.durdur)


if __name__ == "__main__":
    pencere = tk.Tk()
    uygulama = SesliUyariAraci(pencere)
    pencere.mainloop()
