// Theme.swift
// Beacon
//
// Restrained visual language: system typography, one accent colour, soft rounded surfaces,
// hairline separators, no decorative gradients or animation noise. Supports dark mode through
// semantic system colours.

import SwiftUI
import UIKit

enum Theme {
    // Accent — a calm indigo that reads correctly in both appearances.
    static let accent = Color(red: 0.40, green: 0.50, blue: 0.98)
    static let success = Color(red: 0.18, green: 0.72, blue: 0.47)
    static let warning = Color(red: 0.93, green: 0.63, blue: 0.18)
    static let danger = Color(red: 0.91, green: 0.32, blue: 0.34)
    static let neutral = Color.secondary

    static let background = Color(uiColor: UIColor { trait in
        trait.userInterfaceStyle == .dark
            ? UIColor(red: 0.055, green: 0.055, blue: 0.070, alpha: 1)
            : UIColor(red: 0.965, green: 0.965, blue: 0.975, alpha: 1)
    })

    static let surface = Color(uiColor: UIColor { trait in
        trait.userInterfaceStyle == .dark
            ? UIColor(red: 0.098, green: 0.098, blue: 0.118, alpha: 1)
            : UIColor.white
    })

    static let surfaceElevated = Color(uiColor: UIColor { trait in
        trait.userInterfaceStyle == .dark
            ? UIColor(red: 0.132, green: 0.132, blue: 0.156, alpha: 1)
            : UIColor(red: 0.949, green: 0.949, blue: 0.965, alpha: 1)
    })

    static let separator = Color(uiColor: UIColor { trait in
        trait.userInterfaceStyle == .dark
            ? UIColor.white.withAlphaComponent(0.08)
            : UIColor.black.withAlphaComponent(0.07)
    })

    static let radius: CGFloat = 22
    static let innerRadius: CGFloat = 14
    static let screenPadding: CGFloat = 18
    static let cardPadding: CGFloat = 16
    static let spacing: CGFloat = 14

    static func colour(for tone: Tone) -> Color {
        switch tone {
        case .accent: return accent
        case .success: return success
        case .warning: return warning
        case .danger: return danger
        case .neutral: return neutral
        }
    }
}

extension Font {
    static let beaconDisplay = Font.system(size: 28, weight: .semibold, design: .default)
    static let beaconTitle = Font.system(size: 20, weight: .semibold, design: .default)
    static let beaconHeadline = Font.system(size: 16, weight: .semibold, design: .default)
    static let beaconBody = Font.system(size: 15, weight: .regular, design: .default)
    static let beaconCaption = Font.system(size: 12, weight: .medium, design: .default)
    static let beaconTiny = Font.system(size: 11, weight: .medium, design: .default)
    static let beaconNumber = Font.system(size: 22, weight: .semibold, design: .rounded)
    static let beaconMono = Font.system(size: 12, weight: .regular, design: .monospaced)
}

// MARK: - Surfaces

struct CardSurface: ViewModifier {
    var padding: CGFloat = Theme.cardPadding

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .strokeBorder(Theme.separator, lineWidth: 0.8)
            )
    }
}

extension View {
    func beaconCard(padding: CGFloat = Theme.cardPadding) -> some View {
        modifier(CardSurface(padding: padding))
    }
}

struct ScreenBackground: ViewModifier {
    func body(content: Content) -> some View {
        content.background(Theme.background.ignoresSafeArea())
    }
}

extension View {
    func beaconScreen() -> some View {
        modifier(ScreenBackground())
    }
}

// MARK: - Button styles

struct BeaconPrimaryButtonStyle: ButtonStyle {
    var tint: Color = Theme.accent

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.beaconHeadline)
            .foregroundStyle(.white)
            .padding(.horizontal, 18)
            .padding(.vertical, 11)
            .background(tint.opacity(configuration.isPressed ? 0.75 : 1), in: Capsule())
    }
}

struct BeaconSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.beaconHeadline)
            .foregroundStyle(.primary)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Theme.surfaceElevated, in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.separator, lineWidth: 0.8))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct BeaconDestructiveButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.beaconHeadline)
            .foregroundStyle(Theme.danger)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Theme.danger.opacity(configuration.isPressed ? 0.22 : 0.12), in: Capsule())
    }
}
