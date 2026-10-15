import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'kannada_quotes.dart';
import 'quote_rotation.dart';

/// Home hero: the Karnataka flag and map with the current Kannada quote at its centre.
/// Only the quote and its counter fade when [quoteTickerProvider] moves on; the flag and name stay put.
class KarnatakaQuoteHero extends ConsumerWidget {
  const KarnatakaQuoteHero({super.key});

  static const asset = 'assets/images/karnataka_hero.png';

  static const _cream = Color(0xFFFFF6E0);
  static const _gold = Color(0xFFF2C94C);
  static const _leaf = Color(0xFF0F2A14);
  static const _soil = Color(0xFF3B2412);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final quote = ref.watch(quoteTickerProvider);
    final fade = MediaQuery.disableAnimationsOf(context) ? Duration.zero : const Duration(milliseconds: 600);
    final textScale = MediaQuery.textScalerOf(context).scale(1).clamp(1.0, 1.3);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final width = constraints.maxWidth;
          final height = (width * 0.98).clamp(300.0, 440.0) * textScale;
          return Semantics(
            container: true,
            excludeSemantics: true,
            label: quote == null
                ? 'Harvestique'
                : 'Harvestique. Quote ${quote.number} of ${kannadaQuotes.length}: ${quote.kannada}',
            child: ClipRRect(
              borderRadius: BorderRadius.circular(28),
              child: SizedBox(
                height: height,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    Image.asset(asset, fit: BoxFit.cover, filterQuality: FilterQuality.medium),
                    // Darkest behind the quote; the flag's yellow and red stay visible at the edges.
                    const DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: RadialGradient(
                          center: Alignment(0, 0.08),
                          radius: 0.9,
                          colors: [Color(0xD90A140B), Color(0x8C0A140B), Color(0x140A140B)],
                          stops: [0, 0.55, 1],
                        ),
                      ),
                    ),
                    // Leaf green at the top, soil brown at the bottom.
                    DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [
                            _leaf.withValues(alpha: 0.6),
                            _leaf.withValues(alpha: 0),
                            _soil.withValues(alpha: 0),
                            _soil.withValues(alpha: 0.9),
                          ],
                          stops: const [0, 0.24, 0.72, 1],
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(22, 20, 22, 16),
                      child: Column(
                        children: [
                          const _Wordmark(),
                          Expanded(
                            child: AnimatedSwitcher(
                              duration: fade,
                              switchInCurve: Curves.easeOut,
                              switchOutCurve: Curves.easeIn,
                              child: quote == null
                                  ? const SizedBox.shrink()
                                  : _Quote(key: ValueKey(quote.number), quote: quote, width: width - 44),
                            ),
                          ),
                          AnimatedSwitcher(
                            duration: fade,
                            child: quote == null
                                ? const SizedBox.shrink()
                                : _Counter(key: ValueKey(quote.number), number: quote.number),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _Wordmark extends StatelessWidget {
  const _Wordmark();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const Text(
          'HARVESTIQUE',
          maxLines: 1,
          style: TextStyle(
            color: KarnatakaQuoteHero._cream,
            fontSize: 20,
            fontWeight: FontWeight.w700,
            letterSpacing: 6,
            shadows: [Shadow(color: Colors.black54, blurRadius: 8)],
          ),
        ),
        const SizedBox(height: 8),
        // Karnataka yellow and red, as a thin rule under the name.
        ClipRRect(
          borderRadius: BorderRadius.circular(2),
          child: const SizedBox(
            width: 44,
            height: 3,
            child: Row(
              children: [
                Expanded(child: ColoredBox(color: Color(0xFFF2C500))),
                Expanded(child: ColoredBox(color: Color(0xFFD6252B))),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _Quote extends StatelessWidget {
  const _Quote({super.key, required this.quote, required this.width});

  final KannadaQuote quote;
  final double width;

  @override
  Widget build(BuildContext context) {
    final size = (width / 13).clamp(19.0, 27.0);
    return Center(
      // Scales down, never clips, when a long quote meets a small screen or large system text.
      child: FittedBox(
        fit: BoxFit.scaleDown,
        child: SizedBox(
          width: width,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '“',
                style: TextStyle(
                  color: KarnatakaQuoteHero._gold,
                  fontSize: size * 1.9,
                  height: 0.9,
                  fontWeight: FontWeight.w700,
                ),
              ),
              Text(
                quote.kannada,
                textAlign: TextAlign.center,
                locale: const Locale('kn', 'IN'),
                style: TextStyle(
                  color: KarnatakaQuoteHero._cream,
                  fontSize: size,
                  fontWeight: FontWeight.w700,
                  height: 1.6, // room for Kannada vowel signs above and below the line
                  shadows: const [Shadow(color: Colors.black87, blurRadius: 14)],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Counter extends StatelessWidget {
  const _Counter({super.key, required this.number});

  final int number;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.35),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: KarnatakaQuoteHero._gold.withValues(alpha: 0.6)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Text(
          '$number / ${kannadaQuotes.length}',
          style: const TextStyle(
            color: KarnatakaQuoteHero._cream,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            letterSpacing: 1,
          ),
        ),
      ),
    );
  }
}
