// Combine surface mock — ONLY for typechecking Beacon's SwiftUI code on Linux.

import Foundation

public protocol ObservableObject: AnyObject {}

@propertyWrapper
public struct Published<Value> {
    public var wrappedValue: Value

    public init(wrappedValue: Value) {
        self.wrappedValue = wrappedValue
    }

    public init() where Value: ExpressibleByNilLiteral {
        self.wrappedValue = nil
    }

    public var projectedValue: Published<Value> { self }
}

@propertyWrapper
public struct StateObject<ObjectType: ObservableObject> {
    private let storage: ObjectType?

    public init(wrappedValue: @autoclosure @escaping () -> ObjectType) {
        self.storage = wrappedValue()
    }

    public var wrappedValue: ObjectType {
        guard let storage else { fatalError("StateObject storage unavailable in shim") }
        return storage
    }

    public var projectedValue: ObjectType { wrappedValue }
}
