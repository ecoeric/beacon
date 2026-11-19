// SwiftUI modifier surface mock — ONLY for typechecking on Linux.

import Foundation
import Combine
import UIKit

@MainActor
public extension View {
    // text / label styling
    func font(_ font: Font) -> Self { self }
    func fontWeight(_ weight: Font.Weight) -> Self { self }
    func bold() -> Self { self }
    func foregroundStyle(_ color: Color) -> Self { self }
    func tint(_ color: Color?) -> Self { self }
    func lineLimit(_ number: Int?) -> Self { self }
    func lineLimit(_ range: ClosedRange<Int>) -> Self { self }
    func lineLimit(_ range: PartialRangeFrom<Int>) -> Self { self }
    func minimumScaleFactor(_ factor: CGFloat) -> Self { self }
    func multilineTextAlignment(_ alignment: TextAlignment) -> Self { self }
    func fixedSize(horizontal: Bool = false, vertical: Bool = false) -> Self { self }
    func tracking(_ value: CGFloat) -> Self { self }
    func lineSpacing(_ value: CGFloat) -> Self { self }
    func monospacedDigit() -> Self { self }
    func textSelection(_ selection: TextSelection?) -> Self { self }
    func textInputAutocapitalization(_ value: TextInputAutocapitalization?) -> Self { self }
    func autocorrectionDisabled(_ disabled: Bool = true) -> Self { self }
    func keyboardType(_ type: UIKeyboardType) -> Self { self }
    func textContentType(_ type: String?) -> Self { self }
    func scrollDismissesKeyboard(_ mode: ScrollDismissesKeyboardMode) -> Self { self }

    // layout
    func padding(_ length: CGFloat) -> Self { self }
    func padding(_ edges: Edge.Set, _ length: CGFloat? = nil) -> Self { self }
    func frame(width: CGFloat? = nil, height: CGFloat? = nil, alignment: Alignment = .center) -> Self { self }
    func frame(
        minWidth: CGFloat? = nil,
        idealWidth: CGFloat? = nil,
        maxWidth: CGFloat? = nil,
        minHeight: CGFloat? = nil,
        idealHeight: CGFloat? = nil,
        maxHeight: CGFloat? = nil,
        alignment: Alignment = .center
    ) -> Self { self }
    func fixedSize() -> Self { self }
    func layoutPriority(_ value: Double) -> Self { self }
    func clipped() -> Self { self }
    func clipShape<S: Shape>(_ shape: S) -> Self { self }
    func contentShape<S: Shape>(_ shape: S) -> Self { self }
    func ignoresSafeArea() -> Self { self }

    // surfaces
    func background(_ color: Color) -> Self { self }
    func background(_ color: Color, in shape: some Shape) -> Self { self }
    func background<V: View>(_ view: V) -> Self { self }
    func overlay<V: View>(_ view: V) -> Self { self }
    func overlay(_ color: Color) -> Self { self }
    func opacity(_ value: Double) -> Self { self }
    func redacted(reason: RedactionReasons) -> Self { self }
    func cornerRadius(_ radius: CGFloat, antialiased: Bool = true) -> Self { self }

    // interaction
    func disabled(_ disabled: Bool) -> Self { self }
    func allowsHitTesting(_ enabled: Bool) -> Self { self }
    func onTapGesture(count: Int = 1, perform: @escaping () -> Void) -> Self { self }
    func onAppear(perform: (() -> Void)? = nil) -> Self { self }
    func onDisappear(perform: (() -> Void)? = nil) -> Self { self }
    func onChange<V: Equatable>(of value: V, _ action: @escaping (V, V) -> Void) -> Self { self }
    func task(_ action: @escaping () async -> Void) -> Self { self }
    func task<ID: Equatable>(id: ID, _ action: @escaping () async -> Void) -> Self { self }
    func id<ID: Hashable>(_ id: ID) -> Self { self }
    func refreshable(_ action: @escaping () async -> Void) -> Self { self }
    func focused(_ binding: FocusState<Bool>) -> Self { self }
    func focused<Value: Equatable>(_ binding: FocusState<Value>, equals value: Value) -> Self { self }

    // navigation / presentation
    func navigationTitle(_ title: String) -> Self { self }
    func navigationBarTitleDisplayMode(_ mode: NavigationBarTitleDisplayMode) -> Self { self }
    func toolbar<Content: View>(@ViewBuilder content: () -> Content) -> Self { self }
    func tabItem<Content: View>(@ViewBuilder label: () -> Content) -> Self { self }
    func badge(_ count: Int) -> Self { self }
    func tag<V: Hashable>(_ tag: V) -> Self { self }
    func sheet<Content: View>(
        isPresented: Binding<Bool>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping () -> Content
    ) -> Self { self }
    func sheet<Item: Identifiable, Content: View>(
        item: Binding<Item?>,
        onDismiss: (() -> Void)? = nil,
        @ViewBuilder content: @escaping (Item) -> Content
    ) -> Self { self }
    func presentationDetents(_ detents: Set<PresentationDetent>) -> Self { self }
    func confirmationDialog<Actions: View, Message: View>(
        _ title: String,
        isPresented: Binding<Bool>,
        titleVisibility: Visibility = .automatic,
        @ViewBuilder actions: () -> Actions,
        @ViewBuilder message: () -> Message
    ) -> Self { self }

    // styles
    func buttonStyle<S: ButtonStyle>(_ style: S) -> Self { self }
    func labelStyle<S: LabelStyle>(_ style: S) -> Self { self }
    func pickerStyle<S: PickerStyle>(_ style: S) -> Self { self }
    func controlSize(_ size: ControlSize) -> Self { self }

    // accessibility
    func accessibilityLabel(_ label: String) -> Self { self }
    func accessibilityHint(_ hint: String) -> Self { self }
    func accessibilityElement(children: AccessibilityChildBehavior = .ignore) -> Self { self }
    func accessibilityHidden(_ hidden: Bool) -> Self { self }

    // environment
    func environmentObject<T: ObservableObject>(_ object: T) -> Self { self }
    func preferredColorScheme(_ colorScheme: ColorScheme?) -> Self { self }
    func modifier<M: ViewModifier>(_ modifier: M) -> Self { self }
}

public extension Image {
    func resizable(capInsets: EdgeInsets = EdgeInsets(), resizingMode: String = "stretch") -> Image { self }
    func scaledToFill() -> Image { self }
    func scaledToFit() -> Image { self }
}

public struct EdgeInsets {
    public init() {}
}

public extension Shape {
    func fill(_ color: Color) -> Self { self }
    func stroke(_ color: Color, lineWidth: CGFloat = 1) -> Self { self }
    func strokeBorder(_ color: Color, lineWidth: CGFloat = 1) -> Self { self }
}

public struct LabeledContent: View {
    public init(_ title: String, value: String) {}
    public var body: Never { fatalError() }
}
