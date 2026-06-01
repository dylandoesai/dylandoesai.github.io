This folder is no longer required.

The wake song ("Papi's Home" by Drake) is played by Spotify via the
AppleScript bridge, not from a local MP3.

To configure the song, paste the Spotify track URI into:

    config/config.json -> wake_song.spotify_uri

To get the URI: open Spotify, find the track, right-click ->
Share -> Copy Spotify URI (or Copy Song Link). Both formats work
(spotify:track:... and https://open.spotify.com/track/...).

This folder is kept as a fallback in case you ever want to switch to a
local file-based wake song later.
