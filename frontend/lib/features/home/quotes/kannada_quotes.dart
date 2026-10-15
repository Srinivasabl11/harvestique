// Harvestique 100 Emotional Kannada Quotes, exactly as numbered in
// docs/Harvestique_100_Emotional_Kannada_Quotes.pdf. Do not edit wording or order here without updating the PDF.

/// One numbered quote; [english] is present only where the source gives a translation (quotes 1-10).
class KannadaQuote {
  const KannadaQuote({required this.number, required this.kannada, this.english});

  final int number;
  final String kannada;
  final String? english;
}

const List<KannadaQuote> kannadaQuotes = [
  // Farmer & Soil
  KannadaQuote(
    number: 1,
    kannada: 'ರೈತನ ಕೈಯಲ್ಲಿ ಮಣ್ಣು ಮಾತ್ರವಲ್ಲ, ಒಂದು ಕುಟುಂಬದ ಭವಿಷ್ಯ ಇರುತ್ತದೆ.',
    english: 'In a farmer’s hands lies not just soil, but a family’s future.',
  ),
  KannadaQuote(
    number: 2,
    kannada: 'ಅವನು ಮಣ್ಣಿನಲ್ಲಿ ಬೀಜ ಬಿತ್ತುತ್ತಾನೆ, ಆದರೆ ಕನಸುಗಳನ್ನು ಮನಸ್ಸಿನಲ್ಲಿ ಬಿತ್ತುತ್ತಾನೆ.',
    english: 'He plants seeds in the soil, but dreams in his heart.',
  ),
  KannadaQuote(
    number: 3,
    kannada: 'ರೈತನ ಬೆವರಿನ ಪ್ರತಿಯೊಂದು ಹನಿಯಲ್ಲೂ ನಮ್ಮ ಅನ್ನದ ಒಂದು ಕಣವಿದೆ.',
    english: 'Every drop of a farmer’s sweat lives in a grain of our food.',
  ),
  KannadaQuote(
    number: 4,
    kannada: 'ತನ್ನ ಹಸಿವಿಗಿಂತ ಮೊದಲು ನಮ್ಮ ಹಸಿವನ್ನು ಯೋಚಿಸುವವನೇ ರೈತ.',
    english: 'A farmer is the one who thinks of our hunger before his own.',
  ),
  KannadaQuote(
    number: 5,
    kannada: 'ಮಣ್ಣನ್ನು ಮುಟ್ಟಿದ ಆ ಕೈಗಳು, ಕೋಟ್ಯಂತರ ಜೀವಗಳನ್ನು ಮುಟ್ಟುತ್ತವೆ.',
    english: 'Those hands that touch the soil touch millions of lives.',
  ),
  KannadaQuote(
    number: 6,
    kannada: 'ರೈತನ ಮುಖದ ನಗು, ಒಂದು ಹೊಲದ ಯಶಸ್ಸಿಗಿಂತ ದೊಡ್ಡ ಕೊಯ್ಲು.',
    english: 'A farmer’s smile is a harvest greater than any field can produce.',
  ),
  KannadaQuote(
    number: 7,
    kannada: 'ಅವನ ಕಾಲಿಗೆ ಮಣ್ಣು ಅಂಟಿರಬಹುದು; ಆದರೆ ಅವನ ಕನಸುಗಳು ಆಕಾಶ ಮುಟ್ಟುತ್ತವೆ.',
    english: 'His feet may carry soil, but his dreams reach the sky.',
  ),
  KannadaQuote(
    number: 8,
    kannada: 'ರೈತನು ಮಣ್ಣನ್ನು ಬೆಳೆಸುವುದಿಲ್ಲ; ಮಣ್ಣಿನೊಂದಿಗೆ ಬದುಕನ್ನು ಬೆಳೆಸುತ್ತಾನೆ.',
    english: 'A farmer doesn’t merely grow crops; he grows life with the soil.',
  ),
  KannadaQuote(
    number: 9,
    kannada: 'ಅವನ ಬೆವರನ್ನು ನಾವು ಕಾಣುವುದಿಲ್ಲ, ಆದರೆ ಅದರ ರುಚಿಯನ್ನು ಪ್ರತಿದಿನ ಸವಿಯುತ್ತೇವೆ.',
    english: 'We may not see his sweat, but we taste its reward every day.',
  ),
  KannadaQuote(
    number: 10,
    kannada: 'ಒಬ್ಬ ರೈತನ ಮೌನದ ಹಿಂದೆ ಸಾವಿರ ಮಾತುಗಳಿವೆ.',
    english: 'Behind a farmer’s silence are a thousand stories.',
  ),
  // Seed, Crop & Hope
  KannadaQuote(number: 11, kannada: 'ಒಂದು ಸಣ್ಣ ಬೀಜದೊಳಗೆ, ಒಂದು ದೊಡ್ಡ ಮನೆಯ ಕನಸು ಮಲಗಿರುತ್ತದೆ.'),
  KannadaQuote(number: 12, kannada: 'ಬೀಜ ಬಿತ್ತುವಾಗ ರೈತನು ಬೆಳೆಗಿಂತ ಮೊದಲು ಭರವಸೆಯನ್ನು ಬಿತ್ತುತ್ತಾನೆ.'),
  KannadaQuote(number: 13, kannada: 'ಮಣ್ಣಿನೊಳಗೆ ಹೂತುಹೋದ ಬೀಜ, ನಾಳೆಯ ಬದುಕಾಗಿ ಹೊರಬರುತ್ತದೆ.'),
  KannadaQuote(number: 14, kannada: 'ಪ್ರತಿ ಮೊಳಕೆಯೂ ‘ನಾಳೆ ಒಳ್ಳೆಯದಾಗುತ್ತದೆ’ ಎಂಬ ಪ್ರಕೃತಿಯ ಮಾತು.'),
  KannadaQuote(number: 15, kannada: 'ಬೀಜಕ್ಕೆ ಮಣ್ಣು ಬೇಕು; ರೈತನಿಗೆ ಭರವಸೆ ಬೇಕು.'),
  KannadaQuote(number: 16, kannada: 'ಒಂದು ಕಾಳಿನ ಹಿಂದೆ ಒಂದು ಋತು, ಒಂದು ಕುಟುಂಬ, ಒಂದು ಕನಸು.'),
  KannadaQuote(number: 17, kannada: 'ಬೆಳೆ ಬೆಳೆದು ನಿಂತಾಗ, ರೈತನ ಕನಸೂ ಅದರ ಜೊತೆ ಎದ್ದು ನಿಲ್ಲುತ್ತದೆ.'),
  KannadaQuote(number: 18, kannada: 'ಕೊಯ್ಲಿನ ದಿನ ಹೊಲ ಮಾತ್ರ ತುಂಬುವುದಿಲ್ಲ; ರೈತನ ಕಣ್ಣುಗಳೂ ತುಂಬುತ್ತವೆ.'),
  KannadaQuote(number: 19, kannada: 'ಮೊಳಕೆಯಾದ ಪ್ರತಿಯೊಂದು ಬೀಜವೂ ರೈತನ ಹೃದಯದ ಒಂದು ತುಂಡು.'),
  KannadaQuote(number: 20, kannada: 'ಇಂದು ಮಣ್ಣಿನಲ್ಲಿರುವ ಬೀಜ, ನಾಳೆ ಯಾರದೋ ತಟ್ಟೆಯಲ್ಲಿರುವ ಅನ್ನ.'),
  // Kaveri & Water
  KannadaQuote(number: 21, kannada: 'ಕಾವೇರಿ ಹರಿಯುವುದು ನದಿಯಾಗಿ ಅಲ್ಲ, ತಾಯಿಯಂತೆ.'),
  KannadaQuote(number: 22, kannada: 'ಕಾವೇರಿಯ ಪ್ರತಿಯೊಂದು ಹನಿಯಲ್ಲೂ ಕರುನಾಡಿನ ಸಾವಿರ ಕನಸುಗಳು ಹರಿಯುತ್ತವೆ.'),
  KannadaQuote(number: 23, kannada: 'ಕಾವೇರಿ ತೀರದ ಮಣ್ಣು, ನೀರಿನ ಜೊತೆ ಬದುಕಿನ ಕಥೆ ಬರೆಯುತ್ತದೆ.'),
  KannadaQuote(number: 24, kannada: 'ಒಂದು ಹನಿ ನೀರು ರೈತನಿಗೆ ಕೇವಲ ನೀರಲ್ಲ; ಅದು ಒಂದು ಭರವಸೆ.'),
  KannadaQuote(number: 25, kannada: 'ಕಾವೇರಿ ನಿಂತರೆ ನದಿ ಮಾತ್ರ ನಿಲ್ಲುವುದಿಲ್ಲ; ಅನೇಕ ಕನಸುಗಳು ನಿಲ್ಲುತ್ತವೆ.'),
  KannadaQuote(number: 26, kannada: 'ಕಾವೇರಿಯ ನೀರು ಹೊಲ ತಲುಪಿದಾಗ, ರೈತನ ಹೃದಯದಲ್ಲಿ ಭರವಸೆ ಮೊಳೆಯುತ್ತದೆ.'),
  KannadaQuote(number: 27, kannada: 'ನದಿಯ ಹರಿವಿನಲ್ಲಿ ನೀರು ಮಾತ್ರವಲ್ಲ, ಪೀಳಿಗೆಗಳ ಬದುಕು ಹರಿಯುತ್ತದೆ.'),
  KannadaQuote(number: 28, kannada: 'ಕಾವೇರಿಯ ಹನಿ, ರೈತನ ಕಣ್ಣೀರಿನ ಬೆಲೆ ತಿಳಿದಿದೆ.'),
  KannadaQuote(number: 29, kannada: 'ನೀರು ಉಳಿಸುವುದು ಎಂದರೆ, ನಾಳೆಯ ರೈತನ ಕನಸನ್ನು ಉಳಿಸುವುದು.'),
  KannadaQuote(number: 30, kannada: 'ಕಾವೇರಿಯ ಪ್ರತಿಯೊಂದು ಅಲೆ, ‘ಬೆಳೆ ಬೆಳೆಯಲಿ, ಬದುಕು ಉಳಿಯಲಿ’ ಎಂದು ಹಾಡುತ್ತದೆ.'),
  // Rain & Nature
  KannadaQuote(number: 31, kannada: 'ಮೊದಲ ಮಳೆಯ ಹನಿ ಬಿದ್ದಾಗ, ರೈತನ ಕಣ್ಣಲ್ಲಿ ಮೊದಲು ಮಳೆ ಬರುತ್ತದೆ.'),
  KannadaQuote(number: 32, kannada: 'ಆಕಾಶ ಮೋಡವಾದಾಗ, ರೈತನ ಮನಸ್ಸಿನಲ್ಲಿ ಹಸಿರು ಮೂಡುತ್ತದೆ.'),
  KannadaQuote(number: 33, kannada: 'ಮಳೆ ಬಂದ ದಿನ ರೈತನಿಗೆ ಅದು ಋತುವಲ್ಲ, ಹಬ್ಬ.'),
  KannadaQuote(number: 34, kannada: 'ಮಳೆಯ ಪ್ರತಿಯೊಂದು ಹನಿಯೂ ಮಣ್ಣಿನ ಹೃದಯಕ್ಕೆ ಬರೆದ ಪತ್ರ.'),
  KannadaQuote(number: 35, kannada: 'ಮಳೆ ಸುರಿದಾಗ ಮಣ್ಣು ಮಾತ್ರ ನೆನೆಯುವುದಿಲ್ಲ; ರೈತನ ಆಶೆಯೂ ನೆನೆಯುತ್ತದೆ.'),
  KannadaQuote(number: 36, kannada: 'ಒಣಗಿದ ಹೊಲಕ್ಕೆ ಮಳೆ ಬಂದ ಕ್ಷಣ, ಅದು ಪ್ರಕೃತಿಯ ಅಪ್ಪುಗೆಯಂತೆ.'),
  KannadaQuote(number: 37, kannada: 'ಮಳೆಯ ಸದ್ದು ಕೇಳಿದಾಗ, ರೈತನ ಹೃದಯದಲ್ಲಿ ಬೆಳೆಗಳ ಹೆಜ್ಜೆ ಕೇಳಿಸುತ್ತದೆ.'),
  KannadaQuote(number: 38, kannada: 'ಪ್ರಕೃತಿ ಕೊಡುವ ಪ್ರತಿಯೊಂದು ಹನಿಗೂ ರೈತ ತನ್ನ ಬದುಕಿನಿಂದ ಉತ್ತರಿಸುತ್ತಾನೆ.'),
  KannadaQuote(number: 39, kannada: 'ಮಳೆ ಕಡಿಮೆಯಾದಾಗ ರೈತನ ಪ್ರಾರ್ಥನೆ ಹೆಚ್ಚಾಗುತ್ತದೆ.'),
  KannadaQuote(number: 40, kannada: 'ಮೋಡದ ಕಡೆ ನೋಡುವ ಕಣ್ಣುಗಳಲ್ಲಿ, ಒಂದು ಕುಟುಂಬದ ನಾಳೆ ಇರುತ್ತದೆ.'),
  // Family & Farmer
  KannadaQuote(number: 41, kannada: 'ರೈತನ ಹೊಲದಲ್ಲಿ ಬೆಳೆಯುವುದು ಬೆಳೆ ಮಾತ್ರವಲ್ಲ; ಅವನ ಮಕ್ಕಳ ಕನಸುಗಳೂ ಹೌದು.'),
  KannadaQuote(number: 42, kannada: 'ಅವನು ಬಿತ್ತುವ ಪ್ರತಿಯೊಂದು ಬೀಜದ ಹಿಂದೆ ತನ್ನ ಮಗುವಿನ ಭವಿಷ್ಯವನ್ನು ನೋಡುತ್ತಾನೆ.'),
  KannadaQuote(number: 43, kannada: 'ತನ್ನ ಮಕ್ಕಳಿಗೆ ಉತ್ತಮ ಬದುಕು ಕೊಡಲು, ರೈತ ಮಣ್ಣಿನೊಂದಿಗೆ ಹೋರಾಡುತ್ತಾನೆ.'),
  KannadaQuote(number: 44, kannada: 'ಅವನ ಕೈಯಲ್ಲಿ ಮಣ್ಣಿನ ಗುರುತು; ಅವನ ಹೃದಯದಲ್ಲಿ ಮನೆಯವರ ಮುಖ.'),
  KannadaQuote(number: 45, kannada: 'ರೈತನಿಗೆ ಕೊಯ್ಲು ಎಂದರೆ ಬೆಳೆ ಸಿಗುವುದು ಮಾತ್ರವಲ್ಲ, ಮನೆಯ ನಗು ಮರಳುವುದು.'),
  KannadaQuote(number: 46, kannada: 'ಒಂದು ಹೊಲದ ಹಸಿರಿನ ಹಿಂದೆ ಒಂದು ಕುಟುಂಬದ ತ್ಯಾಗ ಅಡಗಿದೆ.'),
  KannadaQuote(number: 47, kannada: 'ಅವನ ಕಣ್ಣಿನ ಕನಸುಗಳು, ಅವನ ಮಕ್ಕಳ ಕಣ್ಣಿನ ಭವಿಷ್ಯವಾಗುತ್ತವೆ.'),
  KannadaQuote(number: 48, kannada: 'ರೈತನ ಮನೆಯ ದೀಪ, ಅವನ ಹೊಲದ ಹಸಿರಿನಿಂದ ಬೆಳಗುತ್ತದೆ.'),
  KannadaQuote(number: 49, kannada: 'ಅವನು ಮಣ್ಣನ್ನು ಹಿಡಿದಿರುವ ಕೈಗಳಿಂದಲೇ ತನ್ನ ಮಕ್ಕಳ ಕೈ ಹಿಡಿಯುತ್ತಾನೆ.'),
  KannadaQuote(number: 50, kannada: 'ರೈತನ ಶ್ರಮದ ಮೊದಲ ಫಲ ಅವನ ಕುಟುಂಬದ ನಗು.'),
  // Karnataka / Karunadu
  KannadaQuote(number: 51, kannada: 'ಕರುನಾಡಿನ ಮಣ್ಣಿನ ವಾಸನೆಗೆ ಸಾವಿರ ವರ್ಷಗಳ ನೆನಪು ಇದೆ.'),
  KannadaQuote(number: 52, kannada: 'ಈ ಮಣ್ಣಿನಲ್ಲಿ ಬೆಳೆದ ಬೆಳೆ, ಕೇವಲ ಆಹಾರವಲ್ಲ; ಅದು ನಮ್ಮ ಗುರುತು.'),
  KannadaQuote(number: 53, kannada: 'ಕರುನಾಡಿನ ಹೊಲಗಳು ಹಸಿರಾಗಿದ್ದರೆ, ನಮ್ಮ ನೆನಪುಗಳೂ ಹಸಿರಾಗಿರುತ್ತವೆ.'),
  KannadaQuote(number: 54, kannada: 'ಈ ನೆಲ ರೈತನ ಬೆವರಿನಿಂದ ಪವಿತ್ರವಾಗಿದೆ.'),
  KannadaQuote(number: 55, kannada: 'ಮಣ್ಣಿನ ಪರಿಮಳದಲ್ಲಿ ನಮ್ಮ ಊರಿನ ಬಾಲ್ಯದ ನೆನಪು ಅಡಗಿದೆ.'),
  KannadaQuote(number: 56, kannada: 'ಕರುನಾಡಿನ ಪ್ರತಿಯೊಂದು ಕಾಳಿನಲ್ಲೂ ಒಂದು ಹಳ್ಳಿಯ ಕಥೆ ಇದೆ.'),
  KannadaQuote(number: 57, kannada: 'ಈ ಮಣ್ಣು ನಮ್ಮನ್ನು ಬೆಳೆಸಿದೆ; ಈಗ ಅದನ್ನು ನಾವು ಕಾಪಾಡಬೇಕು.'),
  KannadaQuote(number: 58, kannada: 'ಹೊಲದ ಹಸಿರು ಕರುನಾಡಿನ ಹೃದಯದ ಬಣ್ಣ.'),
  KannadaQuote(number: 59, kannada: 'ಮಣ್ಣಿನ ಸುವಾಸನೆ ಬಂದಾಗ, ದೂರದಲ್ಲಿದ್ದ ಊರು ಮನಸ್ಸಿಗೆ ಹತ್ತಿರವಾಗುತ್ತದೆ.'),
  KannadaQuote(number: 60, kannada: 'ಕರುನಾಡಿನ ಮಣ್ಣನ್ನು ಮುಟ್ಟಿದರೆ, ಮನೆಯ ನೆನಪು ಬರುತ್ತದೆ.'),
  // Karnataka Crops
  KannadaQuote(number: 61, kannada: 'ಕಾಫಿಯ ಪ್ರತಿಯೊಂದು ಪರಿಮಳದಲ್ಲೂ ಮಲೆನಾಡಿನ ಮಳೆಯ ನೆನಪಿದೆ.'),
  KannadaQuote(number: 62, kannada: 'ರಾಗಿಯ ಪ್ರತಿಯೊಂದು ಕಾಳಿನಲ್ಲೂ ಕರುನಾಡಿನ ಶಕ್ತಿ ಇದೆ.'),
  KannadaQuote(number: 63, kannada: 'ಕಬ್ಬಿನ ಸಿಹಿಯ ಹಿಂದೆ ರೈತನ ಕಹಿಯಾದ ಶ್ರಮವಿದೆ.'),
  KannadaQuote(number: 64, kannada: 'ತೆಂಗಿನ ಮರದ ಪ್ರತಿಯೊಂದು ಎಲೆಯಲ್ಲೂ ಕರಾವಳಿಯ ಗಾಳಿ ಉಸಿರಾಡುತ್ತದೆ.'),
  KannadaQuote(number: 65, kannada: 'ಅಡಿಕೆಯ ತೋಟದ ಹಸಿರಿನಲ್ಲಿ ಪೀಳಿಗೆಯ ಪರಿಶ್ರಮ ಅಡಗಿದೆ.'),
  KannadaQuote(number: 66, kannada: 'ಜೋಳದ ಕಾಳುಗಳಲ್ಲಿ ಉತ್ತರ ಕರ್ನಾಟಕದ ಮಣ್ಣಿನ ಗಟ್ಟಿತನ ಇದೆ.'),
  KannadaQuote(number: 67, kannada: 'ಅರಿಶಿನದ ಬಣ್ಣದಲ್ಲಿ ರೈತನ ಬದುಕಿನ ಹೊಳಪು ಇದೆ.'),
  KannadaQuote(number: 68, kannada: 'ಬಾಳೆಯ ಸಿಹಿಯಲ್ಲಿ ಒಂದು ಮನೆಯ ಪ್ರೀತಿಯಿದೆ.'),
  KannadaQuote(number: 69, kannada: 'ಪ್ರತಿ ಬೆಳೆಯ ರುಚಿಯ ಹಿಂದೆ ಅದರ ನೆಲದ ಆತ್ಮವಿದೆ.'),
  KannadaQuote(number: 70, kannada: 'ಕರುನಾಡಿನ ಬೆಳೆಗಳನ್ನು ಸವಿಯುವುದು, ಕರುನಾಡಿನ ಕಥೆಯನ್ನು ಸವಿದಂತೆ.'),
  // Generations & Heritage
  KannadaQuote(number: 71, kannada: 'ತಾತ ಬಿತ್ತಿದ ಬೀಜ, ಇಂದು ಮೊಮ್ಮಗನ ಬದುಕನ್ನು ಪೋಷಿಸುತ್ತದೆ.'),
  KannadaQuote(number: 72, kannada: 'ಕೆಲವು ಹೊಲಗಳು ಕೇವಲ ಜಮೀನಲ್ಲ; ಅವು ಕುಟುಂಬದ ನೆನಪುಗಳು.'),
  KannadaQuote(number: 73, kannada: 'ಪೀಳಿಗೆಗಳು ಬದಲಾಗಬಹುದು, ಮಣ್ಣಿನ ಮೇಲಿನ ಪ್ರೀತಿ ಬದಲಾಗುವುದಿಲ್ಲ.'),
  KannadaQuote(number: 74, kannada: 'ಅಜ್ಜನ ಕೈಯಿಂದ ಬಂದ ಕೃಷಿ ಜ್ಞಾನ, ಮೊಮ್ಮಗನ ಕೈಯಲ್ಲಿ ಮುಂದುವರಿಯುತ್ತದೆ.'),
  KannadaQuote(number: 75, kannada: 'ಒಂದು ಹೊಲದ ಕಥೆ, ಒಂದು ಕುಟುಂಬದ ಇತಿಹಾಸ.'),
  KannadaQuote(number: 76, kannada: 'ಮಣ್ಣನ್ನು ಕಾಪಾಡುವುದು ಎಂದರೆ ನಮ್ಮ ಪೂರ್ವಜರ ನೆನಪನ್ನು ಕಾಪಾಡುವುದು.'),
  KannadaQuote(number: 77, kannada: 'ಪೀಳಿಗೆಗಳಿಂದ ಉಳಿದ ಮಣ್ಣು, ಪೀಳಿಗೆಗಳಿಗೆ ಉಳಿಯಬೇಕಾದ ಸಂಪತ್ತು.'),
  KannadaQuote(number: 78, kannada: 'ರೈತನ ಪರಂಪರೆ ಪುಸ್ತಕಗಳಲ್ಲಿ ಅಲ್ಲ, ಹೊಲಗಳಲ್ಲಿ ಜೀವಿಸುತ್ತದೆ.'),
  KannadaQuote(number: 79, kannada: 'ಬೀಜ ಬದಲಾಗಬಹುದು; ಆದರೆ ಅದನ್ನು ಕಾಪಾಡುವ ಕೈಗಳ ಪ್ರೀತಿ ಒಂದೇ.'),
  KannadaQuote(number: 80, kannada: 'ಮಣ್ಣಿನೊಂದಿಗೆ ಬೆಳೆದ ಸಂಸ್ಕೃತಿಯನ್ನು ಕಾಲವೂ ಅಳಿಸಲಾರದು.'),
  // Harvestique / Emotional Brand Lines
  KannadaQuote(number: 81, kannada: 'ಮಣ್ಣಿನ ಕಥೆಯನ್ನು ಜಗತ್ತಿನ ಹೃದಯಕ್ಕೆ ತಲುಪಿಸುವ ಪ್ರಯಾಣ — Harvestique.'),
  KannadaQuote(number: 82, kannada: 'ಒಂದು ರೈತನ ಶ್ರಮದಿಂದ, ಒಂದು ಜಗತ್ತಿನ ಊಟದವರೆಗೆ.'),
  KannadaQuote(number: 83, kannada: 'ಮಣ್ಣಿನಿಂದ ಬಂದದ್ದು, ಹೃದಯಕ್ಕೆ ತಲುಪಲಿ.'),
  KannadaQuote(number: 84, kannada: 'ಪ್ರತಿ ಕಾಳಿಗೂ ಒಂದು ಕಥೆ ಇದೆ; ನಾವು ಅದನ್ನು ಕೇಳುತ್ತೇವೆ.'),
  KannadaQuote(number: 85, kannada: 'ರೈತನ ಕೈಯಿಂದ ನಿಮ್ಮ ಕೈಗೆ, ಪ್ರೀತಿಯಿಂದ.'),
  KannadaQuote(number: 86, kannada: 'ಹೊಲದ ಹೃದಯಬಡಿತವನ್ನು ನಿಮ್ಮ ಮನೆಗೆ ತರುವ ಸೇತುವೆ.'),
  KannadaQuote(number: 87, kannada: 'ಬೆಳೆಯ ಹಿಂದೆ ಇರುವ ಮನುಷ್ಯನ ಕಥೆಯನ್ನು ಮರೆಯದಿರೋಣ.'),
  KannadaQuote(number: 88, kannada: 'ರುಚಿಯನ್ನು ಮಾತ್ರವಲ್ಲ, ಅದರ ಹಿಂದೆ ಇರುವ ಬದುಕನ್ನೂ ಅನುಭವಿಸಿ.'),
  KannadaQuote(number: 89, kannada: 'ಮಣ್ಣಿನ ಪರಿಮಳ ಕಳೆದುಹೋಗದಂತೆ, ರೈತನ ಕಥೆ ಮರೆಯಾಗದಂತೆ.'),
  KannadaQuote(number: 90, kannada: 'ಒಂದು ಕಾಳು ನಮ್ಮ ತಟ್ಟೆಗೆ ಬರುವ ಮೊದಲು ಸಾವಿರ ಭಾವನೆಗಳನ್ನು ದಾಟುತ್ತದೆ.'),
  // Deepest / Most Emotional
  KannadaQuote(number: 91, kannada: 'ರೈತನು ತನ್ನ ಕೈಯಲ್ಲಿ ಮಣ್ಣನ್ನು ಹಿಡಿದಾಗ, ಅವನ ಹೃದಯದಲ್ಲಿ ಒಂದು ಕುಟುಂಬದ ಭವಿಷ್ಯ ಇರುತ್ತದೆ.'),
  KannadaQuote(number: 92, kannada: 'ನಾವು ಅನ್ನವನ್ನು ತಿನ್ನುವಾಗ, ಯಾರೋ ಒಬ್ಬರ ಕನಸನ್ನು ಗೌರವಿಸುತ್ತಿದ್ದೇವೆ.'),
  KannadaQuote(number: 93, kannada: 'ನಮ್ಮ ತಟ್ಟೆಯಲ್ಲಿರುವ ಪ್ರತಿಯೊಂದು ಕಾಳಿಗೂ, ಯಾರೋ ಒಬ್ಬರ ಬೆವರಿನ ಕಥೆ ಇದೆ.'),
  KannadaQuote(number: 94, kannada: 'ಹೊಲದಲ್ಲಿ ಬಿದ್ದ ಬೆವರು, ನಮ್ಮ ಮನೆಯಲ್ಲಿ ನಗುವಾಗಿ ಮರಳುತ್ತದೆ.'),
  KannadaQuote(number: 95, kannada: 'ರೈತನ ಕಣ್ಣೀರನ್ನು ಕಂಡ ಮಣ್ಣೇ, ನಮ್ಮ ಅನ್ನವನ್ನು ಬೆಳೆಸುತ್ತದೆ.'),
  KannadaQuote(
    number: 96,
    kannada: 'ಅವನು ಮಣ್ಣಿನಲ್ಲಿ ತನ್ನ ದಿನಗಳನ್ನು ಕಳೆಯುತ್ತಾನೆ, ನಾವು ಆ ಮಣ್ಣಿನ ಫಲದಲ್ಲಿ ನಮ್ಮ ಬದುಕನ್ನು ಕಟ್ಟುತ್ತೇವೆ.',
  ),
  KannadaQuote(number: 97, kannada: 'ಒಬ್ಬ ರೈತನ ಕನಸು ಒಣಗಿದರೆ, ಒಂದು ಹೊಲ ಮಾತ್ರವಲ್ಲ—ಒಂದು ಕುಟುಂಬ ಒಣಗುತ್ತದೆ.'),
  KannadaQuote(number: 98, kannada: 'ಮಣ್ಣನ್ನು ಉಳಿಸುವುದು ಕೃಷಿಯನ್ನು ಉಳಿಸುವುದಲ್ಲ; ನಮ್ಮ ಮುಂದಿನ ಪೀಳಿಗೆಯ ಊಟವನ್ನು ಉಳಿಸುವುದು.'),
  KannadaQuote(number: 99, kannada: 'ರೈತನಿಗೆ ನಾವು ಕೊಡುವ ದೊಡ್ಡ ಗೌರವ, ಅವನ ಬೆಳೆದ ಅನ್ನವನ್ನು ವ್ಯರ್ಥ ಮಾಡದಿರುವುದು.'),
  KannadaQuote(number: 100, kannada: 'ಮಣ್ಣಿನ ಮೇಲೆ ಬಿದ್ದ ಅವನ ಬೆವರಿನ ಹನಿಗಳು, ನಮ್ಮ ಬದುಕಿನ ಮೇಲೆ ಬಿದ್ದ ಆಶೀರ್ವಾದಗಳು.'),
];
