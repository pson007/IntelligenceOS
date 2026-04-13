#!/bin/bash
# start-whisper-recording.sh
# Opens Whisper Transcription and starts a new voice memo recording.
#
# Usage:
#   ./start-whisper-recording.sh              # default name "New Recording"
#   ./start-whisper-recording.sh "Meeting Notes"  # custom recording name

RECORDING_NAME="${1:-}"

osascript <<'APPLESCRIPT_HOME'
-- Step 1: Activate Whisper Transcription (launch if needed)
tell application "Whisper Transcription" to activate
delay 1.5

tell application "System Events"
    tell process "Whisper Transcription"
        -- Step 2: Navigate to Home screen via sidebar
        tell scroll area 1 of group 1 of splitter group 1 of group 1 of splitter group 1 of group 1 of window 1
            tell outline 1
                select row 1
            end tell
        end tell
        delay 0.5
    end tell
end tell
APPLESCRIPT_HOME

# Step 3: Click Voice Memo button (first button in the shortcut grid)
osascript <<'APPLESCRIPT_VOICE'
tell application "System Events"
    tell process "Whisper Transcription"
        tell UI element 3 of scroll area 1 of group 1 of group 2 of splitter group 1 of group 1 of splitter group 1 of group 1 of window 1
            perform action "AXPress" of button 1
        end tell
    end tell
end tell
APPLESCRIPT_VOICE

sleep 1

# Step 4: Optionally set the recording name
if [ -n "$RECORDING_NAME" ]; then
    osascript -e "
    tell application \"System Events\"
        tell process \"Whisper Transcription\"
            tell group 2 of splitter group 1 of group 1 of splitter group 1 of group 1 of window 1
                -- Select all text in the name field and replace
                set focused of text field 1 to true
                set value of text field 1 to \"$RECORDING_NAME\"
            end tell
        end tell
    end tell
    "
fi

# Step 5: Press Start Recording
osascript <<'APPLESCRIPT_RECORD'
tell application "System Events"
    tell process "Whisper Transcription"
        tell group 2 of splitter group 1 of group 1 of splitter group 1 of group 1 of window 1
            perform action "AXPress" of button 1
        end tell
    end tell
end tell
APPLESCRIPT_RECORD

echo "Recording started in Whisper Transcription."
