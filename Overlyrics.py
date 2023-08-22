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

# Constants:
VERBOSE_MODE = False # If true, prints specific logs in the code (for debugging)
CUSTOM_EXCEPT_HOOK = True # If active, errors appear in customized window

PERIOD_TO_UPDATE_TRACK_INFO = 0.1 # Updates the displaying verses every PERIOD_TO_UPDATE_TRACK_INFO seconds

def create_overlay_text():
    # Main window = root
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.overrideredirect(True)

    root.configure(bg="#010311")
    
    root.title("Overlyrics")
    root.iconbitmap(default="icons/overlyrics-icon.ico")

    try:  # Try to load the custom font
        custom_font = font.Font(family="Public Sans", size="22", weight="normal")
    except tk.TclError:
        custom_font = font.Font(family="Arial", size="22", weight="normal")

    # Adding the icon on the left of the main window
    image = tk.PhotoImage(file="icons/gray-icon.png")
    image_label = tk.Label(root, image=image, bg="#010311", highlightbackground="#010311")
    image_label.pack(side=tk.LEFT)  

    # Initial text (while authentication is performed)
    text = tk.Label(root, text="Starting...", font=custom_font, fg="#dfe0eb", bg="#010311")
    text.pack(expand=True)

    # Sets the transparency of the window when clicking, based on the operating system
    if root.tk.call("tk", "windowingsystem") == "win32":
        # For Windows, we use the -alpha attribute
        root.attributes("-alpha", 1.0)  # 1.0 = fully opaque
        root.bind("<Enter>", lambda event: root.attributes("-alpha", 0.1))  # 10% opacity when hovering
        root.bind("<Leave>", lambda event: root.attributes("-alpha", 1.0))

    elif root.tk.call("tk", "windowingsystem") == "aqua":
        # For macOS, we use the attribute -transparentcolor
        root.attributes("-transparentcolor", "#010311")  # NOTE: not tested

    # Allows to drag the window:
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

    root.bind("<ButtonPress-1>", on_drag_start)
    root.bind("<B1-Motion>", on_dragging)

    return root, text, image

def update_overlay_text():
    global actualTrackLyrics, actualVerse, parsed_lyrics, time_str, timestampsInSeconds

    def find_nearest_time(currentProgress, timestampsInSeconds, parsed_lyrics):
        keys_list = list(parsed_lyrics.keys())
        filtered_keys = list(filter(lambda x: timestampsInSeconds[keys_list.index(x)] <= currentProgress, keys_list)) # verses before present time

        if not filtered_keys: # condition where there are no previous verses
            verse = keys_list[0] # returns the first verse
        else:
            verse = max(filtered_keys, key=lambda x: timestampsInSeconds[keys_list.index(x)]) # returns the verse closest to the current time
        return verse

    print("Entered into update_overlay_text()") if VERBOSE_MODE else None    

    if(parsing_in_progress_event.is_set()): # Does not update the overlay if parsing is still being done
        return

    elif(time_str == "TypeError" or time_str == [] or parsed_lyrics == {}):
        print("Lyrics file error.") if VERBOSE_MODE else None
        return "Lyrics file error."
    else:
        # Finds the section of the letter closest to the current time
        currentLyricTime = find_nearest_time(currentProgress, timestampsInSeconds, parsed_lyrics) ## format: HH:MM:SS 
        actualVerse = parsed_lyrics[currentLyricTime]
        
        lyrics_verse_event.set()

def getCurrentTrackInfo():
    current_track = sp.current_user_playing_track() # Get the information of the music being listened to, through the API
    
    # Check if there is music playing
    if current_track is None or (current_track['item'] is None):
        return None  # No track is currently playing
        # NOTE: When the song is changed by the search bar, current_track['item'] initially does not exist.
        # This conditional prevents this from generating an error.
    
    # Extracts relevant information from the track
    artist = current_track['item']['artists'][0]['name']
    track_name = current_track['item']['name']
    is_playing = current_track['is_playing']
    progress_ms = current_track['progress_ms']
    
    # Convert progress_ms to minutes and seconds
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

# Function to update song information
def update_track_info():
    while True:
        global trackName, artistName, currentProgress, isPaused 
        trackName, artistName, currentProgress, isPaused = get_track_info()
        time.sleep(PERIOD_TO_UPDATE_TRACK_INFO)   # Wait PERIOD_TO_UPDATE_TRACK_INFO second before getting the information again

# Function to get the useful song information
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


    update_event.set()  # Flag that variables have been updated

    return trackName, artistName, currentProgress, isPaused

def update_display():
    while True:
        display_lyrics(trackName, artistName, currentProgress, isPaused)
        
        if(trackName is None):
            noMusicIsPlayingOnSpotify()
        else:
            update_overlay_text()

# Function to display the synchronized lyrics
def display_lyrics(trackName, artistName, currentProgress, isPaused):
        global actualTrackLyrics, parsed_lyrics, time_str, timestampsInSeconds

        def getParsedLyrics(lyrics): ## Returns a dict with the entire lyrics and the respectively timestamps
            lines = lyrics.split('\n')  # Divides the lyrics by the verses/lines
            parsed_lyrics = {}  # Dict to storage strings of timestaps and the text lyrics
            time_strs = []

            for line in lines:
                line = line.strip() # Removes the initial backspace
                if line and line.startswith("["):
                    parsed_line = parse_line(line)
                    if parsed_line:
                        time_str, verse_text = parsed_line
                        parsed_lyrics[time_str] = verse_text
                        time_strs.append(time_str)

            return parsed_lyrics, time_strs

        def parse_line(line): # Parses the timestamp and the verse in LRC (Lyric File Format)
            pattern = r'\[(\d{2}:\d{2}\.\d{2})\](.+)'
            match = re.match(pattern, line)

            if match:
                time_str = match.group(1)
                verse_text = match.group(2).strip()
                return time_str, verse_text

            else:
                print("Returning None in parse_line().") if VERBOSE_MODE else None
                return None

        def convert_to_seconds(time_strs):
            total_seconds = []
            for i, time_str in enumerate(time_strs):
                time_obj = datetime.strptime(time_str, "%M:%S.%f")
                seconds = (time_obj.minute * 60) + time_obj.second + (time_obj.microsecond / 1000000)
                total_seconds.append(seconds)
            return total_seconds


        print("trackName in display_lyrics: ", trackName) if VERBOSE_MODE else None

        if (update_track_event.is_set()):
            # If the track has changed, than the new lyrics will be searched and the windows will be updated
            update_track_event.clear()

            searchTerm = "{} {}".format(trackName, artistName)
            lyrics = syncedlyrics.search(searchTerm)

            if (lyrics is None or lyrics.isspace()):
                print("Track not found.") if VERBOSE_MODE else None
            else:
                print("display_lyrics: >>", trackName, "<<") if VERBOSE_MODE else None
                
                actualTrackLyrics = lyrics
                parsed_lyrics, time_str = getParsedLyrics(actualTrackLyrics)             
                timestampsInSeconds = convert_to_seconds(time_str)


            parsing_in_progress_event.clear()


        update_event.wait()  # Waiting until the variables update
        update_event.clear()  # Clearing the update signal event

def spotipyAutenthication():
    # Descontinuado/Deprecated (needs the client_secret, which can't be exposed):
    #sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id="7710e2a5ffe241fd908c556a08452341", client_secret="<SECRET>", 
    # redirect_uri="https://google.com", scope="user-library-read, user-read-playback-state"))
    def authWindowToGetAuthCode():
        def paste_from_clipboard(): # Handle of copy/paste button
            clipboard_content = authWindow.clipboard_get()
            codeEntry.delete(0, tk.END)
            codeEntry.insert(0, clipboard_content)

        def finish_authentication(): # Handle of finish button
            nonlocal auth_code
            auth_code = codeEntry.get()
            authWindow.destroy()

        auth_code = None

        authWindow = tk.Tk()
        authWindow.iconbitmap(default="icons/overlyrics-icon.ico")
        authWindow.title("Overlyrics: autenticação")

        try:  # Trying to load the custom font from the ttf file
           custom_font = font.Font(family="Public Sans", size="12", weight="normal")
        except tk.TclError:
           custom_font = font.Font(family="Arial", size="12", weight="normal")

        # Theme Forest TTK by rdbende
        authWindow.tk.call('source', 'tkinter-themes/forest-dark.tcl')
        ttk.Style().theme_use('forest-dark')

        # Window settings
        width=600
        height=500
        screenwidth = authWindow.winfo_screenwidth()
        screenheight = authWindow.winfo_screenheight()
        alignstr = '%dx%d+%d+%d' % (width, height, (screenwidth - width) / 2, (screenheight - height) / 2)
        authWindow.geometry(alignstr)
        authWindow.resizable(width=False, height=False)

        # Loading logo
        logo_path = "imgs/main-logo-png.png"
        logo_img = tk.PhotoImage(file=logo_path).subsample(6)
        # Displays the logo at the center
        logo_label = tk.Label(authWindow, image=logo_img)
        logo_label.pack(pady=0)

        #>>> LABELS:
        # Code Entry
        codeEntry=ttk.Entry(authWindow)
        codeEntry["font"] = custom_font
        codeEntry["justify"] = "center"
        codeEntry["text"] = ""
        codeEntry.place(x=30,y=250,width=551,height=59)

        # Paste button
        paste_button = ttk.Button(authWindow, text="Colar / Paste", command=paste_from_clipboard)
        paste_button.place(x=475, y=255, width=100, height=50)

        # Text entry
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

        # "Finalizar autenticação / Finish Authentication" button
        finish_button = ttk.Button(authWindow, text="Finalizar autenticação / Finish Authentication", command=finish_authentication, style="Accent.TButton")
        finish_button.place(x=30, y=340, width=551, height=30)

        while(auth_code is None):
            authWindow.mainloop()

        return auth_code

    def PKCE_getAcessToken():
        authURL = authManager.get_authorize_url()

        # [CURRENTLY UNNECESSARY] 
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

    try: # Tries to use the cache to authenticate
        cached_token = authManager.get_cached_token() 
        if cached_token is None:
            raise Exception
        spAPIManager = spotipy.Spotify(auth_manager=authManager)       
    except: # If there is no token in the cache, follow the procedure for manual authentication
        access_token = PKCE_getAcessToken()
        spAPIManager = spotipy.Spotify(auth_manager=authManager, auth=access_token)
        
    return spAPIManager

def noMusicIsPlayingOnSpotify():
    global actualVerse
    actualVerse = "No song is being heard on Spotify."
    lyrics_verse_event.set()

def custom_excepthook(exctype, value, traceback): # If activated, execution time errors opens a windows to handle the error
    root = tk.Tk()
    root.withdraw()  # Hides the main window to show only the error window
    messagebox.showerror("Overlyrics: Error", f"The following error occurred: {value}")
    root.destroy()

# Custom excepthook if activated 
if CUSTOM_EXCEPT_HOOK == True:
    sys.excepthook = custom_excepthook 

# Global variables
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

update_event = threading.Event() # Create an event to flag the variables update
update_track_event = threading.Event() # Create an event to flag the track update
lyrics_verse_event = threading.Event() # Create an event to flag the verse update
parsing_in_progress_event = threading.Event() # Create an event to flag the parsing in progress

# Updates the track infos in a separated thread, every PERIOD_TO_UPDATE_TRACK_INFO seconds
update_thread = threading.Thread(target=update_track_info) 
update_thread.start()

# Updates the main window continuously, in a separate thread
update_display_thread = threading.Thread(target=update_display)
update_display_thread.start()


while True:
    lyrics_verse_event.wait() # Wait for the next verse to updates the main window
    
    # Updates the main window
    overlay_text.config(text=actualVerse)
    overlay_root.update()

    lyrics_verse_event.clear()
