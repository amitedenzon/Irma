import AppKit
import Foundation

let args = Array(CommandLine.arguments.dropFirst())

if args.first == "--version" {
    print("irma-reminders-helper 0.1.0")
    exit(0)
}

let handler = CommandHandler(client: EventKitRemindersClient())

// Read piped stdin (used by `batch` for the JSON body); empty otherwise.
let inputData: Data = {
    let isPiped = isatty(fileno(stdin)) == 0
    return isPiped ? FileHandle.standardInput.readDataToEndOfFile() : Data()
}()

// Establish a real NSApplication event loop so macOS 15 will present the
// TCC permission dialog for EventKit. setActivationPolicy alone is not
// sufficient — the run loop must actually be running.
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

// Schedule the async command handler before starting the run loop so it
// runs as soon as the loop is live. NSApp.run() processes both AppKit
// events and @MainActor Swift concurrency work, so EventKit callbacks
// dispatched to the main queue are handled correctly (no deadlock).
Task { @MainActor in
    do {
        let output = try await handler.handle(args: args, stdin: inputData)
        FileHandle.standardOutput.write(output)
        FileHandle.standardOutput.write(Data("\n".utf8))
        app.terminate(nil)
    } catch let e as CommandError {
        let payload = ["error": e.code, "message": e.message]
        let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        FileHandle.standardError.write(data ?? Data())
        FileHandle.standardError.write(Data("\n".utf8))
        exit(2)
    } catch {
        let payload = ["error": "internal", "message": "\(error)"]
        let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        FileHandle.standardError.write(data ?? Data())
        FileHandle.standardError.write(Data("\n".utf8))
        exit(3)
    }
}

app.run()
