import Foundation

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "--version" {
    print("irma-reminders-helper 0.1.0")
    exit(0)
}
FileHandle.standardError.write(Data("unknown command\n".utf8))
exit(2)
