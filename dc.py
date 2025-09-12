STORY_DATA = {
    'start': {
        'text': "Siz qədim bir məbədin girişində dayanmısınız. Hava qaralır. İki yol var: soldakı mamırlı daşlarla örtülmüş cığır və sağdakı qaranlıq mağara girişi.",
        'choices': [
            {'text': "🌳 Meşə cığırı ilə get", 'goto': 'forest_entrance'},
            {'text': "🦇 Qaranlıq mağaraya daxil ol", 'goto': 'cave_entrance'}
        ]
    },
    'forest_entrance': {
        'text': "Meşənin dərinliklərinə doğru irəliləyirsiniz. Qarşınıza keçilməz, dərin bir yarğan çıxır. O biri tərəfə keçmək üçün bir yola ehtiyacınız var.",
        'choices': [
            {'text': "🌉 İpi istifadə et", 'goto': 'chasm_crossed', 'requires_item': 'ip'},
            {'text': " geri dön", 'goto': 'start'}
        ]
    },
    'chasm_crossed': {
        'text': "İpi möhkəm bir ağaca bağlayıb yarğanın o biri tərəfinə keçirsiniz. Orada, köhnə bir postamentin üzərində parlayan bir medalyon tapırsınız. Medalyonun üzərində qəribə simvollar var. Onu götürürsünüz.",
        'get_item': 'qədim medalyon',
        'choices': [
            {'text': "Geri qayıt", 'goto': 'start'}
        ]
    },
    'cave_entrance': {
        'text': "Mağaranın girişi çox qaranlıqdır. İçəri görmək üçün bir işığa ehtiyacınız var.",
        'choices': [
            {'text': "🔥 Məşəli yandır", 'goto': 'cave_lit', 'requires_item': 'məşəl'},
            {'text': "Koranə irəlilə", 'goto': 'cave_dark_fail'},
            {'text': "Geri dön", 'goto': 'start'}
        ]
    },
    'cave_dark_fail': {
        'text': "Qaranlıqda irəliləməyə çalışırsınız, lakin ayağınız boşluğa düşür və dərin bir çuxura yıxılırsınız. Macəranız burada bitdi. 😔\n\nYeni macəra üçün /macera yazın.",
        'choices': []
    },
    'cave_lit': {
        'text': "Məşəli yandırırsınız və mağaranın divarları işıqlanır. Qarşınızda iki yol görürsünüz: birbaşa irəli gedən dar bir tunel və sağda köhnə taxta bir qapı.",
        'choices': [
            {'text': "Tunnelə gir", 'goto': 'tunnel'},
            {'text': "🚪 Taxta qapını aç", 'goto': 'storage_room'}
        ]
    },
    'storage_room': {
        'text': "Taxta qapını açırsınız. Bura köhnə bir anbardır. Küncdə bir sandığın içində möhkəm bir ip tapırsınız. Onu götürürsünüz.",
        'get_item': 'ip',
        'choices': [
            {'text': "Geri qayıt", 'goto': 'cave_lit'}
        ]
    },
    'tunnel': {
        'text': "Dar tunellə irəliləyirsiniz. Tunelin sonunda divarda üç fərqli rəngdə daş görürsünüz: Qırmızı, Mavi, Yaşıl. Görünür, bu bir tapmacadır. Hansı daşa basırsınız?",
        'choices': [
            {'text': "🔴 Qırmızı daşa bas", 'goto': 'puzzle_fail'},
            {'text': "🔵 Mavi daşa bas", 'goto': 'puzzle_fail'},
            {'text': "🟢 Yaşıl daşa bas", 'goto': 'puzzle_success'}
        ]
    },
    'puzzle_fail': {
        'text': "Səhv daşa basdınız! Yerdən oxlar çıxır və tələyə düşürsünüz. Macəranız burada bitdi. 😔\n\nYeni macəra üçün /macera yazın.",
        'choices': []
    },
    'puzzle_success': {
        'text': "Yaşıl daşa basırsınız. Divarda gizli bir bölmə açılır. İçəridə qədim bir sandıq var. Sandığı açırsınız və içindən parlayan bir qılınc tapırsınız!",
        'get_item': 'əfsanəvi qılınc',
        'choices': [
            {'text': "Qılıncla məbədi tərk et", 'goto': 'win_ending'}
        ]
    },
    'win_ending': {
        'text': "Əfsanəvi qılıncı əldə etdiniz! Məbədin sirlərini açdınız və böyük bir xəzinə ilə geri döndünüz. Qələbə! 🏆\n\nYeni macəra üçün /macera yazın.",
        'choices': []
    }
}

# SİYAHININ ƏN ALTINA BU ƏŞYANI ƏLAVƏ EDİN
STORY_DATA['start']['choices'].append({'text': "🕯️ Məşəl axtar", 'goto': 'find_torch'})
STORY_DATA['find_torch'] = {
    'text': "Məbədin girişindəki daşların arasında yaxşı gizlədilmiş bir məşəl tapırsınız. İndi mağaraya girməyə hazırsınız.",
    'get_item': 'məşəl',
    'choices': [
        {'text': "🦇 Mağaraya daxil ol", 'goto': 'cave_entrance'}
    ]
}

