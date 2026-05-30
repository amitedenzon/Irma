import Foundation

enum AccessStatus: String, Codable {
    case authorized
    case denied
    case restricted
    case notDetermined
}

enum RemindersClientError: Error {
    case calendarNotFound(String)
    case reminderNotFound(String)
    case accessDenied
}

protocol RemindersClient {
    func requestAccess() async throws -> Bool
    func accessStatus() -> AccessStatus
    func ensureList(name: String) async throws -> String
    func listCalendars(prefix: String) async throws -> [CalendarSummary]
    func renameCalendar(calendarId: String, title: String) async throws -> Bool
    func list(calendarId: String) async throws -> [HelperReminder]
    func batch(
        calendarId: String,
        ops: [BatchOp],
        continueOnError: Bool
    ) async throws -> [BatchResult]
    func deleteCalendar(calendarId: String) async throws -> Bool
}
