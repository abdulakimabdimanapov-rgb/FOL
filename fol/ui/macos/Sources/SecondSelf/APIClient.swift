import Foundation

// MARK: - Request/Response Models

struct ChatRequestBody: Codable {
    let message: String
}

struct ChatResponseBody: Codable {
    let response: String
    let actions_taken: [ActionTaken]
}

struct ActionTaken: Codable {
    let tool: String
    let summary: String
}

struct FOLStatusResponse: Codable {
    let status: String
    let version: String
    let llm: [String]
    let tools: Int
}

// MARK: - API Client

@MainActor
final class APIClient {
    static let shared = APIClient()

    private let baseURL = "http://localhost:8754"
    private let session = URLSession.shared

    func onboard(name: String, email: String = "", context: String = "", sessionId: String = "") async throws -> String {
        // FOL doesn't need onboarding — just return a session immediately
        return "fol-session-\(UUID().uuidString.prefix(8))"
    }

    func fetchLatestSession() async throws -> LatestSessionResponse {
        let url = URL(string: "\(baseURL)/api/status")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 10

        guard let (data, response) = try? await session.data(for: request),
              let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200,
              let status = try? JSONDecoder().decode(FOLStatusResponse.self, from: data) else {
            // If server isn't running, throw
            throw APIError.invalidResponse
        }

        return LatestSessionResponse(
            found: status.status == "running",
            session_id: "fol-default",
            name: ProcessInfo.processInfo.environment["USER"] ?? "User",
            has_profile: true,
            has_google_tokens: false
        )
    }

    func transcribeAudio(fileURL: URL) async throws -> String {
        let url = URL(string: "\(baseURL)/api/stt")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30

        // Create multipart form data
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var bodyData = Data()
        // File part
        let fileData = try Data(contentsOf: fileURL)
        let filename = fileURL.lastPathComponent
        bodyData.append("--\(boundary)\r\n".data(using: .utf8)!)
        bodyData.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        bodyData.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        bodyData.append(fileData)
        bodyData.append("\r\n".data(using: .utf8)!)
        bodyData.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = bodyData

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw APIError.invalidResponse
        }

        struct STTResponse: Codable {
            let text: String
        }
        let sttResponse = try JSONDecoder().decode(STTResponse.self, from: data)
        return sttResponse.text
    }

    func saveToObsidian(content: String, category: String) async throws -> Bool {
        let url = URL(string: "\(baseURL)/api/obsidian/save")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 10

        let body: [String: String] = ["content": content, "category": category]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            return false
        }
        return true
    }

    func sendChatMessage(_ message: String, sessionId: String) async throws -> ChatResponseBody {
        let url = URL(string: "\(baseURL)/api/chat")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        let body: [String: String] = ["message": message]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            let detail = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(statusCode: (response as? HTTPURLResponse)?.statusCode ?? 0, detail: detail)
        }

        // Parse FOL response: {"response": "..."}
        struct FOLChatResponse: Codable {
            let response: String
        }
        let folResponse = try JSONDecoder().decode(FOLChatResponse.self, from: data)

        return ChatResponseBody(
            response: folResponse.response,
            actions_taken: []
        )
    }
}

// Keep for compatibility
struct LatestSessionResponse: Codable {
    let found: Bool
    let session_id: String?
    let name: String?
    let has_profile: Bool?
    let has_google_tokens: Bool?
}

enum APIError: LocalizedError {
    case invalidResponse
    case serverError(statusCode: Int, detail: String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid response from server"
        case .serverError(let code, let detail):
            return "Server error (\(code)): \(detail)"
        }
    }
}
