# -*- coding: utf-8 -*-

import tkinter as tk
import tkinter.ttk as ttk
import time
from datetime import datetime
import re
import syncedlyrics
import sched
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import threading
import queue
import sys
from tkinter import messagebox
import tkinter.font as font
import os
import webbrowser

# Constantes:
VERBOSE_MODE = False # Se ativo, printa logs específicos no código (para debugging)
CUSTOM_EXCEPT_HOOK = False # Se ativo, erros aparecem em janela personalizada

PERIOD_TO_UPDATE_TRACK_INFO = 0.1 # Atualiza os versos a cada PERIOD_TO_UPDATE_TRACK_INFO segundos

def create_overlay_text():
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.overrideredirect(True)

    #Configura o background da janela principal (root)
    root.configure(bg="#010311")
    
    root.title("Overlyrics")
    root.iconbitmap(default="icons/overlyrics-icon.ico")

    try:  # Tentar carregar a fonte a partir do arquivo .ttf
        custom_font = font.Font(family="Public Sans", size="22", weight="normal")
    except tk.TclError:
        custom_font = font.Font(family="Arial", size="22", weight="normal")

    image = tk.PhotoImage(file="icons/gray-icon.png")
    image_label = tk.Label(root, image=image, bg="#010311", highlightbackground="#010311")
    image_label.pack(side=tk.LEFT)  # Coloca a imagem ao lado esquerdo do texto

    text = tk.Label(root, text="Starting...", font=custom_font, fg="#dfe0eb", bg="#010311")
    text.pack(expand=True)

    # Define a transparência da janela com base no sistema operacional
    if root.tk.call("tk", "windowingsystem") == "win32":
        # Para Windows, usamos o atributo -alpha
        root.attributes("-alpha", 1.0)  # 1.0 = totalmente opaco
        root.bind("<Enter>", lambda event: root.attributes("-alpha", 0.1))  # 10% de opacidade ao passar o mouse
        root.bind("<Leave>", lambda event: root.attributes("-alpha", 1.0))

    elif root.tk.call("tk", "windowingsystem") == "aqua":
        # Para macOS, usamos o atributo -transparentcolor
        root.attributes("-transparentcolor", "#010311")  # Define a cor de fundo transparente

    # Permite arrastar a janela:
    drag_start_x = 0
    drag_start_y = 0

    def on_drag_start(event):
        nonlocal drag_start_x, drag_start_y
        drag_start_x = event.x
        drag_start_y = event.y

    def on_dragging(event):
        root_x = root.winfo_x() + (event.x - drag_start_x)
        root_y = root.winfo_y() + (event.y - drag_start_y)
        root.geometry(f"+{root_x}+{root_y}")

    # Adiciona funcionalidades de movimentação da janela
    root.bind("<ButtonPress-1>", on_drag_start)
    root.bind("<B1-Motion>", on_dragging)

    return root, text, image

def update_overlay_text():
    global actualTrackLyrics, actualVerse, parsed_lyrics, time_str, timestampsInSeconds

    def find_nearest_time(currentProgress, timestampsInSeconds, parsed_lyrics):
        keys_list = list(parsed_lyrics.keys())
        filtered_keys = list(filter(lambda x: timestampsInSeconds[keys_list.index(x)] <= currentProgress, keys_list)) # versos antes do tempo atual

        if not filtered_keys: # condição em que não há versos anteriores
            verse = keys_list[0] # Retornar o primeiro verso
        else:
            verse = max(filtered_keys, key=lambda x: timestampsInSeconds[keys_list.index(x)]) # retorna o verso mais próximo do tempo atual
        return verse

    print("Entrou em update_overlay_text()") if VERBOSE_MODE else None    

    if(parsing_in_progress_event.is_set()): # Nao atualiza o overlay caso o parsing ainda esteja sendo feito
        return

    elif(time_str == "TypeError" or time_str == [] or parsed_lyrics == {}):
        print("Erro no arquivo de legenda.") if VERBOSE_MODE else None
        return "Erro no arquivo de legenda."
    else:
        # Encontra o trecho da letra mais proxima ao tempo atual:
        currentLyricTime = find_nearest_time(currentProgress, timestampsInSeconds, parsed_lyrics) ## formato HH:MM:SS
        actualVerse = parsed_lyrics[currentLyricTime]
        
        lyrics_verse_event.set()

def getCurrentTrackInfo():
    current_track = sp.current_user_playing_track()  # Obtem as informaçoes da musica sendo escutada, atraves da API
    
    # Verifica se ha' musica sendo tocadda
    if current_track is None or (current_track['item'] is None):
        return None  # No track is currently playing
        #OBS: Quando a musica e' trocada pela barra de pesquisa, current_track['item'] inicialmente nao existe.
        # Este condicional evita que isto gere um erro.
    
    # Extrai informacoes relevantes da track
    artist = current_track['item']['artists'][0]['name']
    track_name = current_track['item']['name']
    is_playing = current_track['is_playing']
    progress_ms = current_track['progress_ms']
    
    # Converte progress_ms para minutos e segundos
    progress_sec = progress_ms // 1000
    progress_min = progress_sec // 60
    progress_sec %= 60
    
    # Return
    return {
        'artist': artist,
        'trackName': track_name,
        'progressMin': progress_min,
        'progressSec': progress_sec,
        'isPlaying': is_playing
    }

# Função para atualizar as informações da música
def update_track_info():
    while True:
        global trackName, artistName, currentProgress, isPaused 
        trackName, artistName, currentProgress, isPaused = get_track_info()
        time.sleep(0.1)  # Aguardar 1 segundo antes de obter as informações novamente

# Função para obter as informações da música
def get_track_info():
    global trackName, artistName, currentProgress, isPaused 

    trackInfo = getCurrentTrackInfo()

    if(trackInfo is None):
        trackName = artistName = currentProgress = isPaused = None
    else:    
        previousTrackName = trackName

        trackName = trackInfo['trackName']
        artistName = trackInfo['artist']
        currentProgress = trackInfo['progressMin'] * 60 + trackInfo['progressSec']
        isPaused = not trackInfo['isPlaying']

        print("get_track_info(): ", trackName) if VERBOSE_MODE else None
        if((previousTrackName != trackName) and (trackName != None) and (trackName != " ")):
            print("get_track_info() - nova musica: " + trackName) if VERBOSE_MODE else None
            update_track_event.set()
            parsing_in_progress_event.set()


    update_event.set()  # Sinalizar que as variáveis foram atualizadas

    return trackName, artistName, currentProgress, isPaused

def update_display():
    while True:
        display_lyrics(trackName, artistName, currentProgress, isPaused)
        
        if(trackName is None):
            noMusicIsPlayingOnSpotify()
        else:
            update_overlay_text()

# Função para exibir as letras sincronizadas
def display_lyrics(trackName, artistName, currentProgress, isPaused):
        global actualTrackLyrics, parsed_lyrics, time_str, timestampsInSeconds

        def getParsedLyrics(lyrics): ## Retorna um dicionário com a letra completa e os timestamps
            lines = lyrics.split('\n')  # Dividir a string em linhas
            parsed_lyrics = {}  # Dicionário para armazenar as time_str e lyric_text
            time_strs = []

            for line in lines:
                line = line.strip() # Remove o espaço inicial
                if line and line.startswith("["):
                    parsed_line = parse_line(line)
                    if parsed_line:
                        time_str, verse_text = parsed_line
                        parsed_lyrics[time_str] = verse_text
                        time_strs.append(time_str)

            return parsed_lyrics, time_strs

        def parse_line(line): # Extrai o tempo e o verso do formato LRC (Lyric File Format) na letra
            pattern = r'\[(\d{2}:\d{2}\.\d{2})\](.+)'
            match = re.match(pattern, line)

            if match:
                time_str = match.group(1)
                verse_text = match.group(2).strip()
                return time_str, verse_text

            else:
                print("Retornando None em parse_line().") if VERBOSE_MODE else None
                return None

        def convert_to_seconds(time_strs):
            total_seconds = []
            for i, time_str in enumerate(time_strs):
                time_obj = datetime.strptime(time_str, "%M:%S.%f")
                seconds = (time_obj.minute * 60) + time_obj.second + (time_obj.microsecond / 1000000)
                total_seconds.append(seconds)
            return total_seconds


        print("trackName em display_lyrics: ", trackName) if VERBOSE_MODE else None

        if (update_track_event.is_set()):
            # Se a música mudou, a nova letra será obtida e a janela sera atualizada
            update_track_event.clear()

            searchTerm = "{} {}".format(trackName, artistName)
            lyrics = syncedlyrics.search(searchTerm)

            if (lyrics is None or lyrics.isspace()):
                print("Música não encontrada.") if VERBOSE_MODE else None
            else:
                print("display_lyrics: >>", trackName, "<<") if VERBOSE_MODE else None
                
                actualTrackLyrics = lyrics
                parsed_lyrics, time_str = getParsedLyrics(actualTrackLyrics)             
                timestampsInSeconds = convert_to_seconds(time_str)


            parsing_in_progress_event.clear()


        update_event.wait()  # Aguardar até que as variáveis sejam atualizadas
        update_event.clear()  # Limpar o sinal de atualização

def spotipyAutenthication():
    # Descontinuado/Deprecated (requer o client_secret, que nao pode ser exposto):
    #sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id="7710e2a5ffe241fd908c556a08452341", client_secret="<SECRET>", 
    # redirect_uri="https://google.com", scope="user-library-read, user-read-playback-state"))
    def authWindowToGetAuthCode():
        def paste_from_clipboard(): # Handle do botao de copiar e colar
            clipboard_content = authWindow.clipboard_get()
            codeEntry.delete(0, tk.END)
            codeEntry.insert(0, clipboard_content)

        def finish_authentication(): # Handle do botao de finalizacao
            nonlocal auth_code
            auth_code = codeEntry.get()
            authWindow.destroy()

        auth_code = None

        authWindow = tk.Tk()
        authWindow.iconbitmap(default="icons/overlyrics-icon.ico")
        authWindow.title("Overlyrics: autenticação")

        try:  # Tentar carregar a fonte a partir do arquivo .ttf
           custom_font = font.Font(family="Public Sans", size="12", weight="normal")
        except tk.TclError:
           custom_font = font.Font(family="Arial", size="12", weight="normal")

        # Theme Forest TTK by rdbende
        authWindow.tk.call('source', 'tkinter-themes/forest-dark.tcl')
        ttk.Style().theme_use('forest-dark')

        # Configurando a janela
        width=600
        height=500
        screenwidth = authWindow.winfo_screenwidth()
        screenheight = authWindow.winfo_screenheight()
        alignstr = '%dx%d+%d+%d' % (width, height, (screenwidth - width) / 2, (screenheight - height) / 2)
        authWindow.geometry(alignstr)
        authWindow.resizable(width=False, height=False)

        # Carrega o logo com tk.PhotoImage()
        logo_path = "imgs/main-logo-png.png"
        logo_img = tk.PhotoImage(file=logo_path).subsample(6)
        # Create a Label to display the logo at the center
        logo_label = tk.Label(authWindow, image=logo_img)
        logo_label.pack(pady=0)

        #>>> LABELS:
        # Entrada do codigo
        codeEntry=ttk.Entry(authWindow)
        codeEntry["font"] = custom_font
        codeEntry["justify"] = "center"
        codeEntry["text"] = ""
        codeEntry.place(x=30,y=250,width=551,height=59)


        # Botao de colar 
        paste_button = ttk.Button(authWindow, text="Colar / Paste", command=paste_from_clipboard)
        paste_button.place(x=475, y=255, width=100, height=50)

        # Textos:
        text_en=tk.Label(authWindow)
        text_en["font"] = custom_font
        text_en["justify"] = "center"
        text_en["text"] = "Proceed the authentication in your browser and paste the code bellow."
        text_en.place(x=0,y=200,width=599,height=36)
        text_br=tk.Label(authWindow)
        text_br["font"] = custom_font
        text_br["justify"] = "center"
        text_br["text"] = "Prossiga com a autenticação pelo navegador e cole o código abaixo."
        text_br.place(x=0,y=160,width=599,height=30)

        # Botao com texto "Finalizar autenticação / Finish Authentication"
        finish_button = ttk.Button(authWindow, text="Finalizar autenticação / Finish Authentication", command=finish_authentication, style="Accent.TButton")
        finish_button.place(x=30, y=340, width=551, height=30)

        while(auth_code is None):
            authWindow.mainloop()

        return auth_code

    def PKCE_getAcessToken():
        authURL = authManager.get_authorize_url()

        # Solving a bug with PyInstaller (github.com/pyinstaller/pyinstaller/issues/6334)
        #lp_key = "LD_LIBRARY_PATH"
        #lp_orig = os.environ.get(f"{lp_key}_ORIG")
        #if lp_orig is not None:
        #    os.environ[lp_key] = lp_orig

        try:
            webbrowser.open_new_tab(authURL)
        except Exception as e:
            raise Exception("Error when opening website in default browser to perform authentication. Please check your internet and try again.") 

        auth_code = authWindowToGetAuthCode() 
        access_token = authManager.get_access_token(code=auth_code, check_cache=False) #
        
        return access_token

    authManager = spotipy.oauth2.SpotifyPKCE(client_id="7710e2a5ffe241fd908c556a08452341", 
                                redirect_uri="https://cezargab.github.io/Overlyrics", 
                                scope="user-read-playback-state",
                                cache_handler= spotipy.CacheFileHandler(".cache_sp"),
                                open_browser=True)

    try: # Tenta utilizar o cache
        authManager.get_cached_token() 
        spAPIManager = spotipy.Spotify(auth_manager=authManager)       
    except: # Caso não haja token no cache, segue o procedimento pra autenticação manual
        access_token = PKCE_getAcessToken()
        print(access_token)
        spAPIManager = spotipy.Spotify(auth_manager=authManager, auth=access_token)
        
    return spAPIManager

def noMusicIsPlayingOnSpotify():
    global actualVerse
    actualVerse = "No song is being heard on Spotify."
    lyrics_verse_event.set()

def custom_excepthook(exctype, value, traceback): # Erros de tempo de execução geram uma janela com o erro.
    # Exibe o erro em uma janela de mensagem
    root = tk.Tk()
    root.withdraw()  # Esconde a janela principal para mostrar apenas a mensagem de erro
    messagebox.showerror("Overlyrics: Erro", f"Ocorreu o seguinte erro: {value}")
    root.destroy()


# Excepthook personalizado
if CUSTOM_EXCEPT_HOOK == True:
    sys.excepthook = custom_excepthook 

# Variáveis globais
trackName = ""
artistName = ""
currentProgress = 0
isPaused = False
actualVerse = ""

actualTrackLyrics = ""
parsed_lyrics = {}
time_str = ""
timestampsInSeconds = []

sp = spotipyAutenthication()

overlay_root, overlay_text, overlay_image = create_overlay_text()
overlay_root.update()

update_event = threading.Event() # Cria um evento para sinalizar a atualização das variáveis
update_track_event = threading.Event() # Cria um evento para sinalizar a atualização da música
lyrics_verse_event = threading.Event() # Cria um evento para sinalizar a atualização do verso
parsing_in_progress_event = threading.Event() # Cria um evento para sinalizar parsing em andamento


# Atualiza a cada PERIOD_TO_UPDATE_TRACK_INFO as informações da música, em uma thread separada
update_thread = threading.Thread(target=update_track_info) 
update_thread.start()

# Atualiza a janela principal constantemente, em uma thread separada
update_display_thread = threading.Thread(target=update_display)
update_display_thread.start()


while True:
    lyrics_verse_event.wait() #Aguarda o próximo verso para ser impresso
    
    # Atualiza o verso na janela
    overlay_text.config(text=actualVerse)
    overlay_root.update()

    lyrics_verse_event.clear()
