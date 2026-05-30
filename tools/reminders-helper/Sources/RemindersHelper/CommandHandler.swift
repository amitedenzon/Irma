import Foundation

struct CommandError: Error {
    let code: String
    let message: String
}

struct CommandHandler {
    let client: RemindersClient

    func handle(args: [String], stdin: Data) async throws -> Data {
        guard let cmd = args.first else {
            throw CommandError(code: "missing_command", message: "no command provided")
        }
        let rest = Array(args.dropFirst())
        switch cmd {
        case "access-status":
            return try encode(["status": client.accessStatus().rawValue])
        case "request-access":
            let granted = try await client.requestAccess()
            if granted {
                return try encode(["granted": true])
            } else {
                return try encode(["granted": false, "reason": "denied"])
            }
        case "ensure-list":
            let name = try requireOption(rest, "--name")
            let id = try await client.ensureList(name: name)
            return try encode(["calendar_id": id])
        case "list":
            let calId = try requireOption(rest, "--calendar-id")
            let rems = try await client.list(calendarId: calId)
            return try encodeCodable(ListOutput(reminders: rems))
        case "batch":
            let calId = try requireOption(rest, "--calendar-id")
            let continueOnError = rest.contains("--continue-on-error")
            let input = try JSONDecoder().decode(BatchInput.self, from: stdin)
            let results = try await client.batch(
                calendarId: calId,
                ops: input.ops,
                continueOnError: continueOnError
            )
            return try encodeCodable(BatchOutput(results: results))
        case "delete-calendar":
            let calId = try requireOption(rest, "--calendar-id")
            let deleted = try await client.deleteCalendar(calendarId: calId)
            return try encode(["deleted": deleted])
        default:
            throw CommandError(code: "unknown_command", message: "unknown command '\(cmd)'")
        }
    }

    private func requireOption(_ args: [String], _ name: String) throws -> String {
        guard let i = args.firstIndex(of: name), i + 1 < args.count else {
            throw CommandError(code: "missing_option", message: "missing \(name) <value>")
        }
        return args[i + 1]
    }

    private func encode(_ payload: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
    }

    func encodeCodable<T: Encodable>(_ value: T) throws -> Data {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys]
        return try enc.encode(value)
    }
}
