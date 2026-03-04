// RECAPTCHAのキー
const RECAPTCHA_KEY = "6Le9HlYqAAAAAJQtQcq3V_tdd73twiM4Rm2wUvn9"

const pokemonDomain = "https://www.pokemoncenter-online.com/"

// 遷移先URLはプロパティ定義
const url = {
    "ajax.base.url": "",
    //ECサイトのトップ画面へ遷移
    "ec.site.top.url": `${pokemonDomain}`,
    //ECサイトのマイページ画面
    "ec.site.my.page.url": `${pokemonDomain}mypage/`,
    //ECサイトのログイン画面  （SC_K02_01）
    "ec.site.login.url": `${pokemonDomain}login/`,
    //ご利用ガイドページへ遷移
    "guide.url": `${pokemonDomain}guide.html`,
    //よくあるご質問・お問い合わせページへ遷移
    "faq.url": "https://www.support.pokemoncenter-online.com/",
    //よくあるご質問・お問い合わせページへ遷移
    "passcode.faq.url": "https://www.support.pokemoncenter-online.com/--68a44a2153c0f0c7064de62d",
    //利用規約ページへ遷移
    "terms.url": `${pokemonDomain}terms.html`,
    //プライバシーポリシーページへ遷移
    "privacy.url": "https://www.pokemon.co.jp/privacy/",
    //特定商取引法に基づく表記へ遷移
    "specific.commercial.transaction.url": `${pokemonDomain}legal.html`,
    //会社概要ページへ遷移
    "company.url": "https://corporate.pokemon.co.jp/",
    //店舗のご案内
    "store.info.url": "https://www.pokemon.co.jp/shop/",
    //新しいブラウザウィンドウで、ポケットモンスター公式サイトを表示する
    "pokemon.official.site.url": "https://www.pokemon.co.jp/",
    //ECサイトのパスワードリセット画面  （SC_K05_01）
    "ec.site.password.reset.url": `${pokemonDomain}reset-password/`,
    //プロパティ定義．ECサイトの利用規約ページ
    "ec.site.agreement.page.url": `${pokemonDomain}lottery-terms`,
    // プロパティ定義．TPCサイトのプライバシーポリシーページ
    "tpc.site.privacy.policy.page.url": "https://www.pokemon.co.jp/privacy/",
    // プロパティ定義．gigyaのURL
    "gigya.url": "https://cdns.us1.gigya.com/js/gigya.js?apikey=4_4wwtwofVtSPz5UsxQAESHg",
    // プロパティ定義．reCAPTCHAのURL
    "recaptcha.url": `https://www.google.com/recaptcha/enterprise.js?render=${RECAPTCHA_KEY}&hl=ja`
}

// エラーメッセージ
const errMsg = {
    "errors.required": "{0}は必須項目です。",
    "errors.unknownError":"意図しない例外が発生しました。",
    "error.SC_O04_09.00001": "認証に失敗しました。もう一度操作を行ってください。",
    "error.SC_O04_09.00002": "メールアドレスまたはパスワードが一致しませんでした。",
    "error.SC_O04_09.00003": "ただいまサイトが大変混雑しています。しばらく経ってから、再度アクセスしてください。",
    "error.SC_O04_09.00004": "エラーが発生しました。時間をおいてから再度お試しください。",
    "error.SC_O04_10.00008": "reCAPTCHAの認証に失敗しました。",
    "error.SC_O04_10.00009": "システムエラーにより、応募受付に失敗した可能性があります。応募履歴をご確認のうえ、再度お試しください。",
    "error.SC_O04_12.00001": "パスコードの認証に失敗しました。再度パスコードを入力して認証を行ってください。",
    "error.SC_O04_12.00002": "パスコードの有効期限が切れています。パスコードを再送のうえ、再度お試しください。",
    "error.SC_O04_12.00003": "パスコードの入力上限に達しました。パスコードを再送のうえ、再度お試しください。",
    "error.SC_O04_12.00004": "ただいまサイトが大変混雑しています。しばらく経ってから、再度アクセスしてください。",
    "error.SC_O04_12.00005": "エラーが発生しました。時間をおいてから再度お試しください。",
}

// ROUTER
const routers = {
    SC_O04_09: '/lottery/login.html', // 抽選ログイン画面
    SC_O04_11: '/lottery/re-agree-to-terms.html', // 利用規約再同意画面
    SC_O04_10: '/lottery/apply.html', // 抽選応募
    SC_O04_08: '/lottery/landing-page.html', // 抽選ランディングページ
    SC_O04_12: '/lottery/login-mfa.html', // パスコード入力
}

// 認証が必要な画面
const needAuthView = [
    routers.SC_O04_10,
]

const ajaxUrl = {
    getLotteryListUrl: `${url["ajax.base.url"]}/a/ltr/api/lottery/v1/get-lottery-list`,
    applyLotteryUrl: `${url["ajax.base.url"]}/a/ltr/api/lottery/v1/apply-lottery`,
    cancelLotteryUrl: `${url["ajax.base.url"]}/a/ltr/api/lottery/v1/cancel-lottery`
}

