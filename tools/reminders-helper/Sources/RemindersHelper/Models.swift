import Foundation

struct HelperReminder: Codable, Equatable {
    let uuid: String
    let title: String
    let notes: String
    let dueDate: String?       // ISO date (YYYY-MM-DD) or nil
    let startDate: String?     // ISO date or nil
    let isCompleted: Bool
    let completionDate: String?  // ISO 8601 timestamp or nil
    let lastModified: String     // ISO 8601 timestamp (always set by EventKit)

    enum CodingKeys: String, CodingKey {
        case uuid
        case title
        case notes
        case dueDate = "due_date"
        case startDate = "start_date"
        case isCompleted = "is_completed"
        case completionDate = "completion_date"
        case lastModified = "last_modified"
    }
}

struct ReminderFields: Codable, Equatable {
    let title: String?
    let notes: String?
    let dueDate: String?
    let startDate: String?
    let isCompleted: Bool?

    enum CodingKeys: String, CodingKey {
        case title
        case notes
        case dueDate = "due_date"
        case startDate = "start_date"
        case isCompleted = "is_completed"
    }
}

struct CalendarSummary: Codable, Equatable {
    let calendarId: String
    let title: String

    enum CodingKeys: String, CodingKey {
        case calendarId = "calendar_id"
        case title
    }
}

struct ListCalendarsOutput: Codable {
    let calendars: [CalendarSummary]
}

enum BatchOp: Codable, Equatable {
    case create(ReminderFields)
    case update(uuid: String, ReminderFields)
    case delete(uuid: String)

    private enum CodingKeys: String, CodingKey {
        case op, fields, uuid
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let op = try c.decode(String.self, forKey: .op)
        switch op {
        case "create":
            let fields = try c.decode(ReminderFields.self, forKey: .fields)
            self = .create(fields)
        case "update":
            let uuid = try c.decode(String.self, forKey: .uuid)
            let fields = try c.decode(ReminderFields.self, forKey: .fields)
            self = .update(uuid: uuid, fields)
        case "delete":
            let uuid = try c.decode(String.self, forKey: .uuid)
            self = .delete(uuid: uuid)
        default:
            throw DecodingError.dataCorruptedError(
                forKey: .op, in: c, debugDescription: "unknown op '\(op)'"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .create(let f):
            try c.encode("create", forKey: .op)
            try c.encode(f, forKey: .fields)
        case .update(let uuid, let f):
            try c.encode("update", forKey: .op)
            try c.encode(uuid, forKey: .uuid)
            try c.encode(f, forKey: .fields)
        case .delete(let uuid):
            try c.encode("delete", forKey: .op)
            try c.encode(uuid, forKey: .uuid)
        }
    }
}

struct BatchInput: Codable {
    let ops: [BatchOp]
}

struct BatchResult: Codable, Equatable {
    let index: Int
    let ok: Bool
    let uuid: String?
    let lastModified: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case index, ok, uuid
        case lastModified = "last_modified"
        case error
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(index, forKey: .index)
        try c.encode(ok, forKey: .ok)
        try c.encodeIfPresent(uuid, forKey: .uuid)
        try c.encodeIfPresent(lastModified, forKey: .lastModified)
        try c.encodeIfPresent(error, forKey: .error)
    }
}

struct BatchOutput: Codable {
    let results: [BatchResult]
}

struct ListOutput: Codable {
    let reminders: [HelperReminder]
}
