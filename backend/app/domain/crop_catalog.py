"""The crop master catalogue: crop groups, the part of the plant each crop is grown for, scientific names, searchable
aliases and the A-Z additions. Pure data plus small lookups, shared by the catalogue seed (app/cli/seed_crops.py),
crop search, the assistant and the crop-health check.

Rules followed here:
* existing crops keep their ids, names and Kannada names; only EMPTY metadata is filled (scientific name, aliases,
  group);
* Kannada names are NOT written for new crops: none were invented, so they show their English name until an admin
  with a verified name adds one;
* an alias is used only when it means the same crop; ambiguous ones ("gooseberry", "orange", "gram" alone for a new
  crop) are left out;
* durations are indicative planning defaults, as in the existing catalogue (perennials use the 365-day convention).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import CropCategory as C
from app.core.enums import CropSeason as S

# the 18 agricultural groups the catalogue is checked against (section 12.3)
GROUPS: dict[str, str] = {
    "cereals": "Cereals and food grains",
    "millets": "Millets and minor millets",
    "pulses": "Pulses and legumes",
    "oilseeds": "Oilseeds",
    "vegetables": "Vegetables",
    "fruits": "Fruits",
    "spices": "Spices and condiments",
    "roots_tubers": "Roots, tubers, bulbs and rhizomes",
    "plantation": "Plantation crops",
    "beverage": "Beverage crops",
    "fibre": "Fibre crops",
    "sugar_starch": "Sugar and starch crops",
    "fodder": "Fodder and forage crops",
    "medicinal_aromatic": "Medicinal and aromatic plants",
    "ornamental": "Ornamental, floricultural and nursery crops",
    "agroforestry": "Agroforestry and commercially cultivated trees",
    "mushrooms": "Mushrooms and other cultivated fungi",
    "other": "Other locally cultivated crops",
}
# the part a farmer usually photographs or sells; the crop-health check adapts its questions to it
PARTS = (
    "leaf",
    "fruit",
    "grain",
    "pod",
    "seed",
    "root",
    "tuber",
    "bulb",
    "rhizome",
    "corm",
    "flower",
    "stem",
    "latex",
    "whole_plant",
    "fungus",
)
DEFAULT_GROUP = {
    C.CEREAL: "cereals",
    C.PULSE: "pulses",
    C.OILSEED: "oilseeds",
    C.VEGETABLE: "vegetables",
    C.FRUIT: "fruits",
    C.SPICE: "spices",
    C.PLANTATION: "plantation",
    C.FLOWER: "ornamental",
    C.FODDER: "fodder",
    C.MEDICINAL: "medicinal_aromatic",
    C.CASH_CROP: "other",
    C.OTHER: "other",
}
DEFAULT_PART = {
    "cereals": "grain",
    "millets": "grain",
    "pulses": "pod",
    "oilseeds": "seed",
    "vegetables": "fruit",
    "fruits": "fruit",
    "spices": "fruit",
    "roots_tubers": "tuber",
    "plantation": "fruit",
    "beverage": "leaf",
    "fibre": "stem",
    "sugar_starch": "stem",
    "fodder": "whole_plant",
    "medicinal_aromatic": "leaf",
    "ornamental": "flower",
    "agroforestry": "leaf",
    "mushrooms": "fungus",
    "other": "leaf",
}


@dataclass(frozen=True, slots=True)
class Meta:
    scientific: str
    aliases: tuple[str, ...]
    group: str
    part: str


def m(scientific: str, aliases: str, group: str, part: str) -> Meta:
    return Meta(scientific, tuple(a.strip() for a in aliases.split(",") if a.strip()), group, part)


# metadata for the 88 crops already in the catalogue (filled only where empty)
EXISTING: dict[str, Meta] = {
    "Aloe Vera": m("Aloe vera", "aloe, ghritkumari", "medicinal_aromatic", "leaf"),
    "Amaranthus": m("Amaranthus spp.", "amaranth, edible amaranth, chaulai", "vegetables", "leaf"),
    "Arecanut": m("Areca catechu", "areca nut, betel nut, supari", "plantation", "fruit"),
    "Ashwagandha": m("Withania somnifera", "indian ginseng, winter cherry", "medicinal_aromatic", "root"),
    "Bajra": m("Pennisetum glaucum", "pearl millet", "millets", "grain"),
    "Banana": m("Musa spp.", "plantain", "fruits", "fruit"),
    "Barnyard Millet": m("Echinochloa frumentacea", "sanwa, jhangora", "millets", "grain"),
    "Beans": m("Phaseolus vulgaris", "french beans, french bean, green beans", "vegetables", "pod"),
    "Beetroot": m("Beta vulgaris", "beet", "roots_tubers", "root"),
    "Bengal Gram": m("Cicer arietinum", "chickpea, chana", "pulses", "pod"),
    "Bitter Gourd": m("Momordica charantia", "karela, bitter melon", "vegetables", "fruit"),
    "Black Gram": m("Vigna mungo", "urad, urd, urad bean", "pulses", "pod"),
    "Black Pepper": m("Piper nigrum", "pepper, kali mirch", "spices", "fruit"),
    "Bottle Gourd": m("Lagenaria siceraria", "lauki, calabash", "vegetables", "fruit"),
    "Brinjal": m("Solanum melongena", "eggplant, aubergine", "vegetables", "fruit"),
    "Browntop Millet": m("Urochloa ramosa", "browntop", "millets", "grain"),
    "Cabbage": m("Brassica oleracea var. capitata", "", "vegetables", "leaf"),
    "Capsicum": m("Capsicum annuum", "bell pepper, shimla mirch, sweet pepper", "vegetables", "fruit"),
    "Cardamom": m("Elettaria cardamomum", "elaichi, small cardamom", "spices", "fruit"),
    "Carrot": m("Daucus carota subsp. sativus", "", "roots_tubers", "root"),
    "Cashew": m("Anacardium occidentale", "cashew nut, cashewnut", "plantation", "fruit"),
    "Castor": m("Ricinus communis", "castor bean", "oilseeds", "seed"),
    "Cauliflower": m("Brassica oleracea var. botrytis", "gobi", "vegetables", "flower"),
    "Chrysanthemum": m("Chrysanthemum spp.", "sevanthi, shevanti", "ornamental", "flower"),
    "Cluster Beans": m("Cyamopsis tetragonoloba", "guar, gawar", "vegetables", "pod"),
    "Coconut": m("Cocos nucifera", "tender coconut", "plantation", "fruit"),
    "Coffee": m("Coffea spp.", "", "beverage", "fruit"),
    "Coriander": m("Coriandrum sativum", "dhania, cilantro", "spices", "leaf"),
    "Cotton": m("Gossypium spp.", "kapas", "fibre", "fruit"),
    "Cowpea": m("Vigna unguiculata", "lobia, karamani", "pulses", "pod"),
    "Crossandra": m("Crossandra infundibuliformis", "kanakambara, firecracker flower", "ornamental", "flower"),
    "Cucumber": m("Cucumis sativus", "kheera", "vegetables", "fruit"),
    "Fenugreek": m("Trigonella foenum-graecum", "methi", "spices", "leaf"),
    "Field Bean": m("Lablab purpureus", "lablab bean, lablab, hyacinth bean, indian bean, avare", "pulses", "pod"),
    "Fodder Maize": m("Zea mays", "", "fodder", "whole_plant"),
    "Fodder Sorghum": m("Sorghum bicolor", "", "fodder", "whole_plant"),
    "Foxtail Millet": m("Setaria italica", "italian millet, navane", "millets", "grain"),
    "Garlic": m("Allium sativum", "lahsun", "spices", "bulb"),
    "Ginger": m("Zingiber officinale", "adrak", "spices", "rhizome"),
    "Grapes": m("Vitis vinifera", "grape", "fruits", "fruit"),
    "Green Chilli": m("Capsicum annuum", "chilli, chili, chillies, hot pepper", "spices", "fruit"),
    "Green Gram": m("Vigna radiata", "mung bean, moong, mung", "pulses", "pod"),
    "Groundnut": m("Arachis hypogaea", "peanut", "oilseeds", "pod"),
    "Guava": m("Psidium guajava", "", "fruits", "fruit"),
    "Horse Gram": m("Macrotyloma uniflorum", "kulthi", "pulses", "pod"),
    "Jackfruit": m("Artocarpus heterophyllus", "", "fruits", "fruit"),
    "Jasmine": m("Jasminum spp.", "mallige", "ornamental", "flower"),
    "Jowar": m("Sorghum bicolor", "sorghum, great millet", "millets", "grain"),
    "Kodo Millet": m("Paspalum scrobiculatum", "kodo", "millets", "grain"),
    "Lemongrass": m("Cymbopogon flexuosus", "lemon grass", "medicinal_aromatic", "leaf"),
    "Little Millet": m("Panicum sumatrense", "samai, saame", "millets", "grain"),
    "Lucerne": m("Medicago sativa", "alfalfa", "fodder", "whole_plant"),
    "Maize": m("Zea mays", "corn", "cereals", "grain"),
    "Mango": m("Mangifera indica", "", "fruits", "fruit"),
    "Marigold": m("Tagetes spp.", "african marigold, french marigold, genda", "ornamental", "flower"),
    "Muskmelon": m("Cucumis melo", "kharbuja, honeydew", "fruits", "fruit"),
    "Mustard": m("Brassica juncea", "indian mustard, rai, sarson", "oilseeds", "pod"),
    "Napier Grass": m("Cenchrus purpureus", "elephant grass", "fodder", "whole_plant"),
    "Okra": m("Abelmoschus esculentus", "lady's finger, ladies finger, ladyfinger, bhindi", "vegetables", "fruit"),
    "Onion": m("Allium cepa", "pyaz", "roots_tubers", "bulb"),
    "Paddy": m("Oryza sativa", "rice", "cereals", "grain"),
    "Papaya": m("Carica papaya", "", "fruits", "fruit"),
    "Pomegranate": m("Punica granatum", "anar", "fruits", "fruit"),
    "Potato": m("Solanum tuberosum", "irish potato, aloo", "roots_tubers", "tuber"),
    "Proso Millet": m("Panicum miliaceum", "common millet", "millets", "grain"),
    "Pumpkin": m("Cucurbita spp.", "indian pumpkin", "vegetables", "fruit"),
    "Radish": m("Raphanus sativus", "mooli", "roots_tubers", "root"),
    "Ragi": m("Eleusine coracana", "finger millet, nachni, mandua", "millets", "grain"),
    "Red Gram": m("Cajanus cajan", "arhar, tur, toor, pigeon pea, pigeonpea", "pulses", "pod"),
    "Ridge Gourd": m("Luffa acutangula", "turai", "vegetables", "fruit"),
    "Rose": m("Rosa spp.", "", "ornamental", "flower"),
    "Rubber": m("Hevea brasiliensis", "", "plantation", "latex"),
    "Safflower": m("Carthamus tinctorius", "kusum", "oilseeds", "seed"),
    "Sapota": m("Manilkara zapota", "chikoo, chiku, sapodilla", "fruits", "fruit"),
    "Sesame": m("Sesamum indicum", "til, gingelly", "oilseeds", "seed"),
    "Snake Gourd": m("Trichosanthes cucumerina", "", "vegetables", "fruit"),
    "Soybean": m("Glycine max", "soyabean, soya bean, soya", "oilseeds", "pod"),
    "Spinach": m("Spinacia oleracea", "palak", "vegetables", "leaf"),
    "Sugarcane": m("Saccharum officinarum", "ganna", "sugar_starch", "stem"),
    "Sunflower": m("Helianthus annuus", "", "oilseeds", "flower"),
    "Sweet Potato": m("Ipomoea batatas", "shakarkand", "roots_tubers", "tuber"),
    "Tea": m("Camellia sinensis", "", "beverage", "leaf"),
    "Tobacco": m("Nicotiana tabacum", "virginia tobacco", "other", "leaf"),
    "Tomato": m("Solanum lycopersicum", "", "vegetables", "fruit"),
    "Tulsi": m("Ocimum tenuiflorum", "holy basil", "medicinal_aromatic", "leaf"),
    "Turmeric": m("Curcuma longa", "haldi", "spices", "rhizome"),
    "Watermelon": m("Citrullus lanatus", "", "fruits", "fruit"),
    "Wheat": m("Triticum aestivum", "", "cereals", "grain"),
}

INDICATIVE = "Indicative duration for planning only; check it against your variety and local practice."
PERENNIAL = (
    "Perennial crop: record one year's crop as one cycle. The 365-day duration is a record-keeping convention, "
    "not an agronomic value."
)
FUNGUS = "Cultivated fungus, not a green plant: the leaf-based crop-health check does not apply."
P = 365  # perennial convention


@dataclass(frozen=True, slots=True)
class NewCrop:
    name: str
    category: C
    days: int
    season: S | None
    meta: Meta

    @property
    def notes(self) -> str:
        if self.meta.group == "mushrooms":
            return FUNGUS
        return PERENNIAL if self.days == P else INDICATIVE


def n(name: str, category: C, days: int, scientific: str, aliases: str, group: str, part: str) -> NewCrop:
    return NewCrop(name, category, days, S.YEAR_ROUND if days == P else None, m(scientific, aliases, group, part))


# A-Z additions (section 12.2) not already in the catalogue under another name or alias
NEW: tuple[NewCrop, ...] = (
    # cereals and pseudo-cereals
    n("Barley", C.CEREAL, 120, "Hordeum vulgare", "jau", "cereals", "grain"),
    n("Oats", C.CEREAL, 110, "Avena sativa", "oat", "cereals", "grain"),
    n("Buckwheat", C.CEREAL, 90, "Fagopyrum esculentum", "kuttu", "cereals", "grain"),
    n("Quinoa", C.CEREAL, 110, "Chenopodium quinoa", "", "cereals", "grain"),
    n("Sweet Corn", C.CEREAL, 90, "Zea mays convar. saccharata", "", "cereals", "grain"),
    # pulses and legumes
    n("Lentil", C.PULSE, 110, "Lens culinaris", "masoor", "pulses", "pod"),
    n("Rajma", C.PULSE, 100, "Phaseolus vulgaris", "kidney bean, red kidney bean", "pulses", "pod"),
    n("Moth Bean", C.PULSE, 75, "Vigna aconitifolia", "matki", "pulses", "pod"),
    n("Field Pea", C.PULSE, 110, "Pisum sativum var. arvense", "yellow pea, dry pea", "pulses", "pod"),
    n("Broad Beans", C.PULSE, 120, "Vicia faba", "fava bean, faba bean", "pulses", "pod"),
    n("Velvet Bean", C.PULSE, 150, "Mucuna pruriens", "mucuna", "pulses", "pod"),
    n("Winged Bean", C.VEGETABLE, 120, "Psophocarpus tetragonolobus", "", "vegetables", "pod"),
    n(
        "Yardlong Bean",
        C.VEGETABLE,
        75,
        "Vigna unguiculata subsp. sesquipedalis",
        "asparagus bean, long bean",
        "vegetables",
        "pod",
    ),
    n("Garden Pea", C.VEGETABLE, 100, "Pisum sativum", "pea, peas, green peas, green pea, matar", "vegetables", "pod"),
    # oilseeds
    n("Linseed", C.OILSEED, 120, "Linum usitatissimum", "flax, flaxseed", "oilseeds", "seed"),
    n("Niger", C.OILSEED, 100, "Guizotia abyssinica", "niger seed, ramtil", "oilseeds", "seed"),
    n("Rapeseed", C.OILSEED, 110, "Brassica napus", "canola", "oilseeds", "pod"),
    n("Oil Palm", C.PLANTATION, P, "Elaeis guineensis", "", "plantation", "fruit"),
    # vegetables
    n("Ash Gourd", C.VEGETABLE, 120, "Benincasa hispida", "wax gourd, winter melon, petha", "vegetables", "fruit"),
    n("Asparagus", C.VEGETABLE, P, "Asparagus officinalis", "", "vegetables", "stem"),
    n("Artichoke", C.VEGETABLE, 150, "Cynara cardunculus var. scolymus", "globe artichoke", "vegetables", "flower"),
    n("Broccoli", C.VEGETABLE, 90, "Brassica oleracea var. italica", "", "vegetables", "flower"),
    n("Brussels Sprouts", C.VEGETABLE, 120, "Brassica oleracea var. gemmifera", "", "vegetables", "leaf"),
    n("Celery", C.VEGETABLE, 120, "Apium graveolens", "", "vegetables", "leaf"),
    n("Chinese Cabbage", C.VEGETABLE, 75, "Brassica rapa subsp. pekinensis", "napa cabbage", "vegetables", "leaf"),
    n("Drumstick", C.VEGETABLE, P, "Moringa oleifera", "moringa", "vegetables", "fruit"),
    n("Endive", C.VEGETABLE, 90, "Cichorium endivia", "", "vegetables", "leaf"),
    n("Ivy Gourd", C.VEGETABLE, P, "Coccinia grandis", "tindora, kundru", "vegetables", "fruit"),
    n("Kale", C.VEGETABLE, 70, "Brassica oleracea var. sabellica", "", "vegetables", "leaf"),
    n("Knol-Khol", C.VEGETABLE, 60, "Brassica oleracea var. gongylodes", "kohlrabi, knol khol", "vegetables", "stem"),
    n("Lettuce", C.VEGETABLE, 60, "Lactuca sativa", "", "vegetables", "leaf"),
    n("Long Melon", C.VEGETABLE, 75, "Cucumis melo var. flexuosus", "kakri, snake melon", "vegetables", "fruit"),
    n("Malabar Spinach", C.VEGETABLE, 90, "Basella alba", "basella", "vegetables", "leaf"),
    n("Pointed Gourd", C.VEGETABLE, P, "Trichosanthes dioica", "parwal", "vegetables", "fruit"),
    n(
        "Shallot",
        C.VEGETABLE,
        75,
        "Allium cepa var. aggregatum",
        "shallots, small onion, sambar onion",
        "roots_tubers",
        "bulb",
    ),
    n("Spring Onion", C.VEGETABLE, 60, "Allium spp.", "green onion, scallion", "vegetables", "leaf"),
    n("Sponge Gourd", C.VEGETABLE, 90, "Luffa aegyptiaca", "smooth gourd", "vegetables", "fruit"),
    n("Spinach Beet", C.VEGETABLE, 60, "Beta vulgaris var. bengalensis", "", "vegetables", "leaf"),
    n("Tinda", C.VEGETABLE, 70, "Praecitrullus fistulosus", "round gourd, indian squash", "vegetables", "fruit"),
    n("Zucchini", C.VEGETABLE, 60, "Cucurbita pepo", "courgette", "vegetables", "fruit"),
    # roots, tubers, corms
    n("Cassava", C.VEGETABLE, 300, "Manihot esculenta", "tapioca", "roots_tubers", "tuber"),
    n("Colocasia", C.VEGETABLE, 180, "Colocasia esculenta", "taro, arbi", "roots_tubers", "corm"),
    n("Elephant Foot Yam", C.VEGETABLE, 240, "Amorphophallus paeoniifolius", "suran", "roots_tubers", "corm"),
    n("Yam", C.VEGETABLE, 270, "Dioscorea spp.", "greater yam", "roots_tubers", "tuber"),
    n("Xanthosoma", C.VEGETABLE, 270, "Xanthosoma sagittifolium", "cocoyam, tannia", "roots_tubers", "corm"),
    n("Turnip", C.VEGETABLE, 60, "Brassica rapa subsp. rapa", "shalgam", "roots_tubers", "root"),
    # fruits
    n("Apple", C.FRUIT, P, "Malus domestica", "", "fruits", "fruit"),
    n("Apricot", C.FRUIT, P, "Prunus armeniaca", "", "fruits", "fruit"),
    n("Avocado", C.FRUIT, P, "Persea americana", "butter fruit", "fruits", "fruit"),
    n("Almond", C.FRUIT, P, "Prunus dulcis", "", "fruits", "fruit"),
    n("Aonla", C.FRUIT, P, "Phyllanthus emblica", "amla, indian gooseberry", "fruits", "fruit"),
    n("Ber", C.FRUIT, P, "Ziziphus mauritiana", "indian jujube", "fruits", "fruit"),
    n("Blueberry", C.FRUIT, P, "Vaccinium spp.", "", "fruits", "fruit"),
    n("Blackberry", C.FRUIT, P, "Rubus spp.", "", "fruits", "fruit"),
    n("Breadfruit", C.FRUIT, P, "Artocarpus altilis", "", "fruits", "fruit"),
    n("Sweet Orange", C.FRUIT, P, "Citrus sinensis", "mosambi, mausambi", "fruits", "fruit"),
    n("Mandarin", C.FRUIT, P, "Citrus reticulata", "kinnow, coorg mandarin", "fruits", "fruit"),
    n("Lemon", C.FRUIT, P, "Citrus limon", "", "fruits", "fruit"),
    n("Lime", C.FRUIT, P, "Citrus aurantiifolia", "acid lime", "fruits", "fruit"),
    n("Custard Apple", C.FRUIT, P, "Annona squamosa", "sitaphal, sugar apple", "fruits", "fruit"),
    n("Cherry", C.FRUIT, P, "Prunus avium", "sweet cherry", "fruits", "fruit"),
    n("Date Palm", C.FRUIT, P, "Phoenix dactylifera", "dates", "fruits", "fruit"),
    n("Dragon Fruit", C.FRUIT, P, "Selenicereus undatus", "pitaya", "fruits", "fruit"),
    n("Fig", C.FRUIT, P, "Ficus carica", "anjeer", "fruits", "fruit"),
    n("Jamun", C.FRUIT, P, "Syzygium cumini", "java plum, black plum", "fruits", "fruit"),
    n("Karonda", C.FRUIT, P, "Carissa carandas", "", "fruits", "fruit"),
    n("Kiwifruit", C.FRUIT, P, "Actinidia deliciosa", "kiwi", "fruits", "fruit"),
    n("Kokum", C.FRUIT, P, "Garcinia indica", "", "fruits", "fruit"),
    n("Litchi", C.FRUIT, P, "Litchi chinensis", "lychee", "fruits", "fruit"),
    n("Mangosteen", C.FRUIT, P, "Garcinia mangostana", "", "fruits", "fruit"),
    n("Passion Fruit", C.FRUIT, P, "Passiflora edulis", "", "fruits", "fruit"),
    n("Peach", C.FRUIT, P, "Prunus persica", "", "fruits", "fruit"),
    n("Pear", C.FRUIT, P, "Pyrus spp.", "", "fruits", "fruit"),
    n("Pineapple", C.FRUIT, P, "Ananas comosus", "", "fruits", "fruit"),
    n("Plum", C.FRUIT, P, "Prunus domestica", "european plum", "fruits", "fruit"),
    n("Raspberry", C.FRUIT, P, "Rubus idaeus", "", "fruits", "fruit"),
    n("Soursop", C.FRUIT, P, "Annona muricata", "", "fruits", "fruit"),
    n("Strawberry", C.FRUIT, 180, "Fragaria x ananassa", "", "fruits", "fruit"),
    n("Tamarind", C.FRUIT, P, "Tamarindus indica", "imli", "fruits", "fruit"),
    n("Tree Tomato", C.FRUIT, P, "Solanum betaceum", "tamarillo", "fruits", "fruit"),
    n("Walnut", C.FRUIT, P, "Juglans regia", "", "fruits", "fruit"),
    n("Water Chestnut", C.FRUIT, 150, "Trapa natans", "singhara", "fruits", "fruit"),
    n("Wood Apple", C.FRUIT, P, "Limonia acidissima", "", "fruits", "fruit"),
    # spices and condiments
    n("Anise", C.SPICE, 120, "Pimpinella anisum", "aniseed", "spices", "seed"),
    n("Cinnamon", C.SPICE, P, "Cinnamomum verum", "dalchini", "spices", "stem"),
    n("Clove", C.SPICE, P, "Syzygium aromaticum", "laung", "spices", "flower"),
    n("Cumin", C.SPICE, 110, "Cuminum cyminum", "jeera", "spices", "seed"),
    n("Curry Leaf", C.SPICE, P, "Murraya koenigii", "kadi patta", "spices", "leaf"),
    n("Dill", C.SPICE, 90, "Anethum graveolens", "sowa, dill seed", "spices", "leaf"),
    n("Fennel", C.SPICE, 150, "Foeniculum vulgare", "saunf", "spices", "seed"),
    n("Nutmeg", C.SPICE, P, "Myristica fragrans", "jaiphal", "spices", "fruit"),
    n("Saffron", C.SPICE, 180, "Crocus sativus", "kesar", "spices", "flower"),
    n("Vanilla", C.SPICE, P, "Vanilla planifolia", "", "spices", "pod"),
    n("Zedoary", C.SPICE, 240, "Curcuma zedoaria", "white turmeric, kachur", "spices", "rhizome"),
    # beverage
    n("Cocoa", C.PLANTATION, P, "Theobroma cacao", "cacao", "beverage", "fruit"),
    # fibre
    n("Jute", C.CASH_CROP, 120, "Corchorus spp.", "", "fibre", "stem"),
    n("Kenaf", C.CASH_CROP, 120, "Hibiscus cannabinus", "mesta", "fibre", "stem"),
    n("Sisal", C.CASH_CROP, P, "Agave sisalana", "", "fibre", "leaf"),
    # fodder
    n("Guinea Grass", C.FODDER, P, "Megathyrsus maximus", "guineagrass", "fodder", "whole_plant"),
    n("Stylo", C.FODDER, P, "Stylosanthes spp.", "stylosanthes", "fodder", "whole_plant"),
    n("Subabul", C.FODDER, P, "Leucaena leucocephala", "leucaena", "fodder", "leaf"),
    # medicinal and aromatic
    n("Basil", C.MEDICINAL, 90, "Ocimum basilicum", "sweet basil", "medicinal_aromatic", "leaf"),
    n("Citronella", C.MEDICINAL, P, "Cymbopogon winterianus", "java citronella", "medicinal_aromatic", "leaf"),
    n("Lavender", C.MEDICINAL, P, "Lavandula angustifolia", "", "medicinal_aromatic", "flower"),
    n("Mint", C.MEDICINAL, 90, "Mentha spp.", "pudina", "medicinal_aromatic", "leaf"),
    n("Psyllium", C.MEDICINAL, 110, "Plantago ovata", "isabgol", "medicinal_aromatic", "seed"),
    n("Rosemary", C.MEDICINAL, P, "Salvia rosmarinus", "", "medicinal_aromatic", "leaf"),
    n("Senna", C.MEDICINAL, 150, "Senna alexandrina", "sonamukhi", "medicinal_aromatic", "leaf"),
    n("Stevia", C.MEDICINAL, P, "Stevia rebaudiana", "", "medicinal_aromatic", "leaf"),
    n("Vetiver", C.MEDICINAL, P, "Chrysopogon zizanioides", "khus", "medicinal_aromatic", "root"),
    # ornamental and floriculture
    n("Dahlia", C.FLOWER, 120, "Dahlia spp.", "", "ornamental", "flower"),
    n("Gerbera", C.FLOWER, P, "Gerbera jamesonii", "", "ornamental", "flower"),
    n("Gladiolus", C.FLOWER, 100, "Gladiolus spp.", "", "ornamental", "flower"),
    n("Hibiscus", C.FLOWER, P, "Hibiscus rosa-sinensis", "", "ornamental", "flower"),
    n("Lotus", C.FLOWER, P, "Nelumbo nucifera", "", "ornamental", "flower"),
    n("Zinnia", C.FLOWER, 90, "Zinnia elegans", "", "ornamental", "flower"),
    # agroforestry and trees
    n("Bamboo", C.OTHER, P, "Bambusa spp.", "", "agroforestry", "stem"),
    n("Eucalyptus", C.OTHER, P, "Eucalyptus spp.", "", "agroforestry", "stem"),
    n("Mahua", C.OTHER, P, "Madhuca longifolia", "", "agroforestry", "flower"),
    n("Neem", C.OTHER, P, "Azadirachta indica", "", "agroforestry", "leaf"),
    n("Sandalwood", C.OTHER, P, "Santalum album", "", "agroforestry", "stem"),
    # other
    n("Betel Leaf", C.CASH_CROP, P, "Piper betle", "betel vine, paan", "other", "leaf"),
    n("Indigo", C.OTHER, 120, "Indigofera tinctoria", "", "other", "leaf"),
    n("Mulberry", C.OTHER, P, "Morus alba", "", "other", "leaf"),
    # cultivated fungi
    n(
        "Mushroom",
        C.OTHER,
        45,
        "Agaricus bisporus / Pleurotus spp.",
        "button mushroom, oyster mushroom",
        "mushrooms",
        "fungus",
    ),
)


def metadata(name: str, category: C | str | None) -> Meta | None:
    """Catalogue metadata for a crop name (existing or new); None for an admin-added crop not listed here."""
    if name in EXISTING:
        return EXISTING[name]
    for crop in NEW:
        if crop.name == name:
            return crop.meta
    return None


def group_and_part(name: str, category: C | str | None, group: str | None) -> tuple[str, str]:
    """The crop's group and main harvested part: from the catalogue, else from its stored group / category."""
    meta = metadata(name, category)
    if meta is not None:
        return meta.group, meta.part
    g = group or DEFAULT_GROUP.get(C(category), "other") if category else (group or "other")
    return g, DEFAULT_PART.get(g, "leaf")
