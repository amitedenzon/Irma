import AppKit
import Foundation

// Establish a GUI activation context so macOS 15 will present the TCC
// permission dialog when request-access is called from a terminal.
NSApplication.shared.setActivationPolicy(.accessory)

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

// Top-level await (Swift 5.7+) keeps EventKit work on the main thread,
// avoiding the deadlock that a DispatchSemaphore-based wait causes when
// EventKit blocks on main-queue dispatch.
do {
    let output = try await handler.handle(args: args, stdin: inputData)
    FileHandle.standardOutput.write(output)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(0)
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
