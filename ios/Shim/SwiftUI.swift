// SwiftUI surface mock — ONLY for typechecking Beacon's SwiftUI code with a Linux Swift compiler.
//
// This is NOT SwiftUI. It reproduces the API shapes Beacon uses (result builders, property
// wrappers, modifiers, shapes) so the real Swift compiler can typecheck every view file. A
// successful run proves the app code is internally consistent against these signatures; it does
// not prove an iOS build (that still needs Xcode).

@_exported import Foundation
@_exported import Combine
import UIKit

// MARK: - View protocol and result builder

@MainActor
public protocol View {
    associatedtype Body: View
    @ViewBuilder var body: Body { get }
}

extension Never: View {
    public var body: Never { fatalError("Never has no body") }
}

public struct EmptyView: View {
    public nonisolated init() {}
    public var body: Never { fatalError() }
}

public struct TupleView<T>: View {
    public nonisolated init() {}
    public var body: Never { fatalError() }
}

public struct _ConditionalContent<TrueContent: View, FalseContent: View>: View {
    public nonisolated init() {}
    public var body: Never { fatalError() }
}

extension Optional: View where Wrapped: View {
    public var body: Never { fatalError() }
}

public struct AnyView: View {
    public nonisolated init<V: View>(_ view: V) {}
    public var body: Never { fatalError() }
}

@resultBuilder
public enum ViewBuilder {
    public static func buildExpression<Content: View>(_ content: Content) -> Content { content }
    public static func buildBlock() -> EmptyView { EmptyView() }
    public static func buildBlock<C: View>(_ c: C) -> C { c }
    public static func buildBlock<C0: View, C1: View>(_ c0: C0, _ c1: C1) -> TupleView<(C0, C1)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View>(_ c0: C0, _ c1: C1, _ c2: C2) -> TupleView<(C0, C1, C2)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View, C3: View>(_ c0: C0, _ c1: C1, _ c2: C2, _ c3: C3) -> TupleView<(C0, C1, C2, C3)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View, C3: View, C4: View>(_ c0: C0, _ c1: C1, _ c2: C2, _ c3: C3, _ c4: C4) -> TupleView<(C0, C1, C2, C3, C4)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View, C3: View, C4: View, C5: View>(_ c0: C0, _ c1: C1, _ c2: C2, _ c3: C3, _ c4: C4, _ c5: C5) -> TupleView<(C0, C1, C2, C3, C4, C5)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View, C3: View, C4: View, C5: View, C6: View>(_ c0: C0, _ c1: C1, _ c2: C2, _ c3: C3, _ c4: C4, _ c5: C5, _ c6: C6) -> TupleView<(C0, C1, C2, C3, C4, C5, C6)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View, C3: View, C4: View, C5: View, C6: View, C7: View>(_ c0: C0, _ c1: C1, _ c2: C2, _ c3: C3, _ c4: C4, _ c5: C5, _ c6: C6, _ c7: C7) -> TupleView<(C0, C1, C2, C3, C4, C5, C6, C7)> { TupleView() }
    public static func buildBlock<C0: View, C1: View, C2: View, C3: View, C4: View, C5: View, C6: View, C7: View, C8: View>(_ c0: C0, _ c1: C1, _ c2: C2, _ c3: C3, _ c4: C4, _ c5: C5, _ c6: C6, _ c7: C7, _ c8: C8) -> TupleView<(C0, C1, C2, C3, C4, C5, C6, C7, C8)> { TupleView() }
    public static func buildIf<Content: View>(_ content: Content?) -> Content? { content }
    public static func buildOptional<Content: View>(_ content: Content?) -> _ConditionalContent<Content, EmptyView>? { nil }
    public static func buildEither<TrueContent: View, FalseContent: View>(first: TrueContent) -> _ConditionalContent<TrueContent, FalseContent> { _ConditionalContent() }
    public static func buildEither<TrueContent: View, FalseContent: View>(second: FalseContent) -> _ConditionalContent<TrueContent, FalseContent> { _ConditionalContent() }
    public static func buildLimitedAvailability<Content: View>(_ content: Content) -> AnyView { AnyView(content) }
}

// MARK: - Stacks and containers

public struct HStack<Content: View>: View {
    public init(alignment: VerticalAlignment = .center, spacing: CGFloat? = nil, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct VStack<Content: View>: View {
    public init(alignment: HorizontalAlignment = .center, spacing: CGFloat? = nil, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct ZStack<Content: View>: View {
    public init(alignment: Alignment = .center, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct Group<Content: View>: View {
    public init(@ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct Spacer: View {
    public init(minLength: CGFloat? = nil) {}
    public var body: Never { fatalError() }
}

public struct ScrollView<Content: View>: View {
    public init(_ axes: Axis.Set = .vertical, showsIndicators: Bool = true, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct LazyVStack<Content: View>: View {
    public init(alignment: HorizontalAlignment = .center, spacing: CGFloat? = nil, pinnedViews: Set<PinnedScrollableViews> = [], @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct LazyVGrid<Content: View>: View {
    public init(columns: [GridItem], alignment: HorizontalAlignment = .center, spacing: CGFloat? = nil, pinnedViews: Set<PinnedScrollableViews> = [], @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct PinnedScrollableViews: OptionSet, Hashable {
    public let rawValue: Int
    public init(rawValue: Int) { self.rawValue = rawValue }
    public static let sectionHeaders = PinnedScrollableViews(rawValue: 1)
}

public struct GridItem {
    public enum Size { case fixed(CGFloat); case flexible(minimum: CGFloat = 10, maximum: CGFloat = .infinity); case adaptive(minimum: CGFloat, maximum: CGFloat = .infinity) }
    public init(_ size: Size, spacing: CGFloat? = nil, alignment: Alignment? = nil) {}
}

public struct ForEach<Data: RandomAccessCollection, ID: Hashable, Content: View>: View {
    public init(_ data: Data, @ViewBuilder content: @escaping (Data.Element) -> Content) where Data.Element: Identifiable, ID == Data.Element.ID {}
    public init(_ data: Data, id: KeyPath<Data.Element, ID>, @ViewBuilder content: @escaping (Data.Element) -> Content) {}
    public var body: Never { fatalError() }
}

public struct Section<Content: View, Header: View, Footer: View>: View {
    public init(@ViewBuilder content: () -> Content, @ViewBuilder header: () -> Header, @ViewBuilder footer: () -> Footer) {}
    public init(@ViewBuilder content: () -> Content, @ViewBuilder header: () -> Header) where Footer == EmptyView {}
    public init(@ViewBuilder content: () -> Content, @ViewBuilder footer: () -> Footer) where Header == EmptyView {}
    public init(_ title: String, @ViewBuilder content: () -> Content) where Header == EmptyView, Footer == EmptyView {}
    public init(@ViewBuilder content: () -> Content) where Header == EmptyView, Footer == EmptyView {}
    public var body: Never { fatalError() }
}

public struct Form<Content: View>: View {
    public init(@ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct DisclosureGroup<Label: View, Content: View>: View {
    public init(isExpanded: Binding<Bool>, @ViewBuilder content: () -> Content, @ViewBuilder label: () -> Label) {}
    public init(@ViewBuilder content: () -> Content, @ViewBuilder label: () -> Label) {}
    public var body: Never { fatalError() }
}

public struct NavigationStack<Content: View>: View {
    public init(@ViewBuilder root: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct TabView<Content: View, SelectionValue: Hashable>: View {
    public init(selection: Binding<SelectionValue>? = nil, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct TabViewStyle {}

public struct Tab<Content: View>: View {
    public init(@ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct GeometryReader<Content: View>: View {
    public init(@ViewBuilder content: @escaping (GeometryProxy) -> Content) {}
    public var body: Never { fatalError() }
}

public struct GeometryProxy {
    public var size: CGSize { CGSize() }
    public struct SafeAreaInsets { public var top: CGFloat = 0; public var bottom: CGFloat = 0 }
    public var safeAreaInsets: SafeAreaInsets { SafeAreaInsets() }
}

// MARK: - Text, images, buttons

public struct Text: View {
    public init(_ content: String) {}
    public init(verbatim: String) {}
    public var body: Never { fatalError() }
}

public struct Label<Title: View, Icon: View>: View {
    public init(@ViewBuilder title: () -> Title, @ViewBuilder icon: () -> Icon) {}
    public var body: Never { fatalError() }
}

public extension Label where Title == Text, Icon == Image {
    init(_ title: String, systemImage: String) { self.init(title: { Text(title) }, icon: { Image(systemName: systemImage) }) }
}

public struct Image: View {
    public init(systemName: String) {}
    public init(uiImage: UIImage) {}
    public init(_ name: String) {}
    public var body: Never { fatalError() }
}

public struct Button<Label: View>: View {
    public init(action: @escaping () -> Void, @ViewBuilder label: () -> Label) {}
    public init(_ title: String, action: @escaping () -> Void) where Label == Text { self.init(action: action, label: { Text(title) }) }
    public init(_ title: String, role: ButtonRole?, action: @escaping () -> Void) where Label == Text { self.init(action: action, label: { Text(title) }) }
    public init(role: ButtonRole?, action: @escaping () -> Void, @ViewBuilder label: () -> Label) {}
    public var body: Never { fatalError() }
}

public struct ProgressView: View {
    public init() {}
    public var body: Never { fatalError() }
}

public struct TextField: View {
    public init(_ title: String, text: Binding<String>) {}
    public init(_ title: String, text: Binding<String>, axis: Axis) {}
    public var body: Never { fatalError() }
}

public struct SecureField: View {
    public init(_ title: String, text: Binding<String>) {}
    public var body: Never { fatalError() }
}

public struct Picker<SelectionValue: Hashable, Content: View>: View {
    public init(_ title: String, selection: Binding<SelectionValue>, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public enum TextAlignment { case leading, center, trailing }

public struct TextSelection {
    public static let enabled = TextSelection()
}

public struct TextInputAutocapitalization {
    public static let never = TextInputAutocapitalization()
    public static let words = TextInputAutocapitalization()
    public static let sentences = TextInputAutocapitalization()
}

public struct ScrollDismissesKeyboardMode {
    public static let interactively = ScrollDismissesKeyboardMode()
    public static let immediately = ScrollDismissesKeyboardMode()
    public static let never = ScrollDismissesKeyboardMode()
    public static let automatically = ScrollDismissesKeyboardMode()
}

public enum Axis {
    case horizontal
    case vertical

    public struct Set: OptionSet {
        public let rawValue: Int
        public init(rawValue: Int) { self.rawValue = rawValue }
        public static let horizontal = Set(rawValue: 1)
        public static let vertical = Set(rawValue: 2)
        public static let all: Set = [.horizontal, .vertical]
    }
}

// MARK: - Alignment and edges

public struct HorizontalAlignment {
    public static let leading = HorizontalAlignment()
    public static let center = HorizontalAlignment()
    public static let trailing = HorizontalAlignment()
}

public struct VerticalAlignment {
    public static let top = VerticalAlignment()
    public static let center = VerticalAlignment()
    public static let bottom = VerticalAlignment()
    public static let firstTextBaseline = VerticalAlignment()
    public static let lastTextBaseline = VerticalAlignment()
}

public struct Alignment {
    public static let center = Alignment()
    public static let leading = Alignment()
    public static let trailing = Alignment()
    public static let top = Alignment()
    public static let bottom = Alignment()
    public static let topLeading = Alignment()
    public static let bottomLeading = Alignment()
    public static let bottomTrailing = Alignment()
    public static let topTrailing = Alignment()
}

public struct Edge {
    public struct Set: OptionSet {
        public let rawValue: Int
        public init(rawValue: Int) { self.rawValue = rawValue }
        public static let top = Set(rawValue: 1)
        public static let bottom = Set(rawValue: 2)
        public static let leading = Set(rawValue: 4)
        public static let trailing = Set(rawValue: 8)
        public static let horizontal: Set = [.leading, .trailing]
        public static let vertical: Set = [.top, .bottom]
        public static let all: Set = [.top, .bottom, .leading, .trailing]
    }
}

public enum Visibility { case automatic, visible, hidden }

public enum RoundedCornerStyle { case circular, continuous }

public enum ButtonRole { case destructive, cancel }

public struct ControlSize {
    public static let small = ControlSize()
    public static let regular = ControlSize()
    public static let large = ControlSize()
}

public struct PresentationDetent: Hashable {
    public static let medium = PresentationDetent()
    public static let large = PresentationDetent()
}

public struct RedactionReasons: OptionSet {
    public let rawValue: Int
    public init(rawValue: Int) { self.rawValue = rawValue }
    public static let placeholder = RedactionReasons(rawValue: 1)
    public static let privacy = RedactionReasons(rawValue: 2)
}

public struct AccessibilityChildBehavior {
    public static let combine = AccessibilityChildBehavior()
    public static let ignore = AccessibilityChildBehavior()
    public static let contain = AccessibilityChildBehavior()
}

public struct NavigationBarTitleDisplayMode {
    public static let automatic = NavigationBarTitleDisplayMode()
    public static let inline = NavigationBarTitleDisplayMode()
    public static let large = NavigationBarTitleDisplayMode()
}

public struct ToolbarItemPlacement {
    public static let automatic = ToolbarItemPlacement()
    public static let topBarLeading = ToolbarItemPlacement()
    public static let topBarTrailing = ToolbarItemPlacement()
    public static let bottomBar = ToolbarItemPlacement()
    public static let navigationBarLeading = ToolbarItemPlacement()
    public static let navigationBarTrailing = ToolbarItemPlacement()
}

public struct ToolbarItem<Content: View>: View {
    public init(placement: ToolbarItemPlacement = .automatic, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

public struct ToolbarItemGroup<Content: View>: View {
    public init(placement: ToolbarItemPlacement = .automatic, @ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

// MARK: - Colours, fonts, shapes

public struct Color: View, Hashable {
    public nonisolated init(red: Double, green: Double, blue: Double) {}
    public nonisolated init(white: Double) {}
    public nonisolated init(uiColor: UIColor) {}
    public nonisolated func opacity(_ value: Double) -> Color { self }
    public nonisolated static let white = Color(white: 1)
    public nonisolated static let black = Color(white: 0)
    public nonisolated static let clear = Color(white: 0)
    public nonisolated static let primary = Color(white: 0)
    public nonisolated static let secondary = Color(white: 0.5)
    public nonisolated static let tertiary = Color(white: 0.65)
    public var body: Never { fatalError() }
}

public struct UnitPoint {
    public static let center = UnitPoint()
    public static let top = UnitPoint()
    public static let bottom = UnitPoint()
    public static let leading = UnitPoint()
    public static let trailing = UnitPoint()
}

public struct LinearGradient: View {
    public init(colors: [Color], startPoint: UnitPoint = .top, endPoint: UnitPoint = .bottom) {}
    public var body: Never { fatalError() }
}

public struct Font {
    public struct Weight: Hashable { public static let ultraLight = Weight(); public static let thin = Weight(); public static let light = Weight(); public static let regular = Weight(); public static let medium = Weight(); public static let semibold = Weight(); public static let bold = Weight(); public static let heavy = Weight(); public static let black = Weight() }
    public enum Design { case `default`, serif, rounded, monospaced }
    public static func system(size: CGFloat, weight: Weight = .regular, design: Design = .default) -> Font { Font() }
    public static let body = Font()
    public static let caption = Font()
    public static let footnote = Font()
    public static let headline = Font()
    public static let subheadline = Font()
    public static let title = Font()
    public static let largeTitle = Font()
}

public protocol Shape: View {}

public struct RoundedRectangle: Shape {
    public init(cornerRadius: CGFloat, style: RoundedCornerStyle = .circular) {}
    public var body: Never { fatalError() }
}

public struct Capsule: Shape {
    public init(style: RoundedCornerStyle = .circular) {}
    public var body: Never { fatalError() }
}

public struct Circle: Shape {
    public init() {}
    public var body: Never { fatalError() }
}

public struct Rectangle: Shape {
    public init() {}
    public var body: Never { fatalError() }
}

// MARK: - Button/label/picker styles

public struct ButtonStyleConfiguration {
    public struct Label: View {
        public var body: Never { fatalError() }
    }
    public let label: Label
    public let isPressed: Bool
}

@MainActor
public protocol ButtonStyle {
    associatedtype Body: View
    typealias Configuration = ButtonStyleConfiguration
    @ViewBuilder func makeBody(configuration: Configuration) -> Body
}

@MainActor
public protocol LabelStyle {}

public struct TitleAndIconLabelStyle: LabelStyle {
    public init() {}
}

public struct IconOnlyLabelStyle: LabelStyle {
    public init() {}
}

public extension LabelStyle where Self == TitleAndIconLabelStyle {
    static var titleAndIcon: TitleAndIconLabelStyle { TitleAndIconLabelStyle() }
}

public extension LabelStyle where Self == IconOnlyLabelStyle {
    static var iconOnly: IconOnlyLabelStyle { IconOnlyLabelStyle() }
}

@MainActor
public protocol PickerStyle {}

public struct SegmentedPickerStyle: PickerStyle {
    public init() {}
}

public extension PickerStyle where Self == SegmentedPickerStyle {
    static var segmented: SegmentedPickerStyle { SegmentedPickerStyle() }
}

// MARK: - View modifiers

@MainActor
public protocol ViewModifier {
    associatedtype Body: View
    typealias Content = _ViewModifierContent<Self>
    @ViewBuilder func body(content: Content) -> Body
}

public struct _ViewModifierContent<Modifier>: View {
    public var body: Never { fatalError() }
}

// MARK: - Property wrappers

@propertyWrapper
public struct State<Value> {
    private final class Box {
        var value: Value
        init(_ value: Value) { self.value = value }
    }

    private let box: Box

    public init(wrappedValue: Value) { box = Box(wrappedValue) }
    public init(initialValue: Value) { box = Box(initialValue) }
    public init() { fatalError("State requires an initial value") }
    public var wrappedValue: Value {
        get { box.value }
        nonmutating set { box.value = newValue }
    }
    public var projectedValue: Binding<Value> {
        Binding(get: { self.box.value }, set: { self.box.value = $0 })
    }
}

@propertyWrapper
public struct Binding<Value> {
    public init(get: @escaping () -> Value, set: @escaping (Value) -> Void) { self.get = get; self.set = set }
    public var wrappedValue: Value { get { self.get() } nonmutating set { self.set(newValue) } }
    public var projectedValue: Binding<Value> { self }
    private let get: () -> Value
    private let set: (Value) -> Void
}

public protocol _FocusStateDefaultValue {
    static var _focusDefault: Self { get }
}

extension Bool: _FocusStateDefaultValue {
    public static var _focusDefault: Bool { false }
}

@propertyWrapper
public struct FocusState<Value> {
    private final class Box {
        var value: Value
        init(_ value: Value) { self.value = value }
    }

    private let box: Box

    public init() where Value: _FocusStateDefaultValue { box = Box(Value._focusDefault) }
    public init() where Value: ExpressibleByNilLiteral { box = Box(nil) }
    public var wrappedValue: Value {
        get { box.value }
        nonmutating set { box.value = newValue }
    }
    public var projectedValue: FocusState<Value> { self }
}

public struct EnvironmentValues {
    public init() {}
    public var dismiss: DismissAction = DismissAction()
    public var scenePhase: ScenePhase = .active
}

public struct DismissAction {
    public init() {}
    public func callAsFunction() {}
}

@propertyWrapper
public struct Environment<Value> {
    public init(_ keyPath: KeyPath<EnvironmentValues, Value>) {}
    public var wrappedValue: Value { fatalError("environment value unavailable in shim") }
}

@propertyWrapper
public struct EnvironmentObject<ObjectType: ObservableObject> {
    public init() {}
    public var wrappedValue: ObjectType { fatalError("environment object unavailable in shim") }
}

// MARK: - Scene phase

public enum ColorScheme { case light, dark }

public enum ScenePhase: Equatable {
    case active
    case inactive
    case background
}

public struct PlainButtonStyle: ButtonStyle {
    public init() {}
    public func makeBody(configuration: Configuration) -> Never { fatalError() }
}

public extension ButtonStyle where Self == PlainButtonStyle {
    static var plain: PlainButtonStyle { PlainButtonStyle() }
}


// MARK: - App and Scene (entry point)

@MainActor
public protocol Scene {
    associatedtype Body: Scene
    @SceneBuilder var body: Body { get }
}

@resultBuilder
public enum SceneBuilder {
    public static func buildBlock<Content: Scene>(_ content: Content) -> Content { content }
}

@MainActor
public protocol App {
    associatedtype Body: Scene
    @SceneBuilder var body: Body { get }
    static func main()
}

public extension App {
    static func main() {}
}

extension Never: Scene {}

public struct WindowGroup<Content: View>: Scene {
    public init(@ViewBuilder content: () -> Content) {}
    public var body: Never { fatalError() }
}

// MARK: - Image rendering (used by the snapshot test)

@MainActor
public final class ImageRenderer<Content: View> {
    public init(content: Content) {}
    public var scale: CGFloat = 1
    public var isOpaque: Bool = false
    public var uiImage: UIImage? { nil }
}

// MARK: - Scroll coordination

public struct ScrollViewReader<Content: View>: View {
    public init(@ViewBuilder content: @escaping (ScrollViewProxy) -> Content) {}
    public var body: Never { fatalError() }
}

public struct ScrollViewProxy {
    public nonisolated init() {}
    public func scrollTo<ID: Hashable>(_ id: ID, anchor: UnitPoint? = nil) {}
}


public struct Animation: Equatable {
    public nonisolated static let `default` = Animation()
    public nonisolated static func easeOut(duration: Double) -> Animation { Animation() }
}

@MainActor
public func withAnimation<Result>(_ animation: Animation? = nil, _ body: () throws -> Result) rethrows -> Result {
    try body()
}
