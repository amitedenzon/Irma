# irma-reminders-helper

EventKit bridge for Irma — read/write the macOS Reminders database via a JSON-over-stdio CLI.

## Build

    swift build -c release --arch arm64 --arch x86_64
    cp .build/apple/Products/Release/RemindersHelper bin/irma-reminders-helper

## Test

    swift test

## Permissions

The helper holds the TCC permission grant for Reminders. First invocation under a new code-signed identity triggers the macOS permission dialog. To force a re-prompt during development:

    tccutil reset Reminders com.irma.reminders-helper
