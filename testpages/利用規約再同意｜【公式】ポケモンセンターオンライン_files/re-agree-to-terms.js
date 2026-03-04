/*------------------------------------------------------------
    terms 抽選利用規約
------------------------------------------------------------*/
$(async function () {

    // 二重押下制御フラグ
    let processingFlag = false;

    const startProcessing = () => {
        processingFlag = true;
    };

    const endProcessing = () => {
        processingFlag = false;
    };

    const gigyaLoad = new Promise((resolve, reject) => {
        $('#gigya-js').attr('src', `${url["gigya.url"]}`);
        $('#gigya-js').on('load', function () {
            resolve()
        }).on("error", function (e) {
            reject(e)
        });
    })

    try {
        await Promise.all([gigyaLoad]);
    } catch (e) {
    }

    const pageInit = function () {
        const termsOfUse = sessionStorage.getItem("termsOfUse");
        const personalPolicy = sessionStorage.getItem("personalPolicy");
        if (termsOfUse !== "true") {
            $("#termsOfUseIframe").prop("src", url["ec.site.agreement.page.url"]);
            $(".termsOfUse").removeClass("hidden")
        } else {
            $("[name='terms']").click();
        }
        if (personalPolicy !== "true") {
            $("#personalPolicyIframe").prop("src", url["tpc.site.privacy.policy.page.url"]);
            $(".personalPolicy").removeClass("hidden")
        } else {
            $("[name='privacyPolicy']").click();
        }
        // 遅延表示
        $("body").removeClass("hidden");
    };

    // 画面初期化
    pageInit();

    // ボタンのdisabled切り替え
    const toggleBtnDisabled = function (status) {
        if (Object.values(status).includes(false)) {
            $('button[type=submit]').prop('disabled', true).addClass('disabled');
            return
        }
        $('button[type=submit]').prop('disabled', false).removeClass('disabled');
    };

    // チェックボックスのステータス取得
    const getCheckboxStatus = function (id, status) {
        status[id] = $('#' + id).prop('checked');
    };

    // チェックボックスのステータ保存
    let checkStatus = {};
    $('.checkboxWrapper input[type=checkbox]').each(function () {
        let id = $(this).attr('id');
        getCheckboxStatus(id, checkStatus);
        $('#' + id).on('click', function () {
            getCheckboxStatus(id, checkStatus);
            toggleBtnDisabled(checkStatus);
        });
    });
    toggleBtnDisabled(checkStatus);

    // 次へ進むボタン
    $("#termsApplyBtn").on("click", function () {

        if(processingFlag){
            // 処理中の場合は、重複実行を防ぐために処理を中止する
            return;
        }

        // 処理中フラグをセット
        startProcessing();

        const preferences = {
            terms: {pokemonCenterOnline: {isConsentGranted: true}},
            privacy: {pokemon: {isConsentGranted: true}},
        }

        // setAccountInfoのコールバック処理
        const callbackReConsent = (response) => {
            // 同意処理のエラーチェック
            if (response.errorCode !== 0) {
                // 同意処理のエラー処理を実装
                endProcessing();
                location.href = routers.SC_O04_09
                return;
            }

            // finalizeRegistrationのコールバック処理
            const callbackFinalizeRegistration = (response) => {
                // 再同意終了処理のエラーチェック
                if (response.errorCode === 403101) {
                    // パスコード認証必要
                    initTFA().then(() => {
                        endProcessing();
                        location.href = routers.SC_O04_12
                        return;
                    });
                } else if (response.errorCode !== 0) {
                    // 再同意終了エラー処理を実装
                    endProcessing();
                    location.href = routers.SC_O04_09
                    return;
                } else {
                    // 正常終了処理を実装、「SC_O04_10_抽選応募」画面に遷移する
                    sessionStorage.setItem("termsOfUse", "true");
                    sessionStorage.setItem("personalPolicy", "true");
                    endProcessing();
                    location.href = routers.SC_O04_10
                }
            }

            // 再同意終了処理で使用するSAP CDC APIメソッドを実行
            window.gigya.accounts.finalizeRegistration({
                callback: callbackFinalizeRegistration, // コールバック関数
                regToken: localStorage.getItem("regToken_" + sessionStorage.getItem("UserId")), // ログイン処理のコールバック関数で取得した値
            })
        }

        // 同意処理で使用するSAP CDC APIメソッドを実行
        window.gigya.accounts.setAccountInfo({
            callback: callbackReConsent, // コールバック関数
            preferences,
            regToken: localStorage.getItem("regToken_" + sessionStorage.getItem("UserId")), // ログイン処理のコールバック関数で取得した値
        })

        // 二要素認証処理初期化
        const initTFA = function() {
            return new Promise((resolve, reject) => {
                const callbackInitTFA = (response) => {
                    // 二要素認証処理初期化のエラーチェック
                    if (response.errorCode === 403110 || response.errorCode === 400006) {
                        // ログイン処理を実装
                        endProcessing();
                        location.href = routers.SC_O04_09
                        reject();
                        return;
                    } else if (response.errorCode === 403048) {
                        // エラー処理を実装
                        $(".comErrorBox > p").text(errMsg["error.SC_O04_09.00003"])
                        $(".comErrorBox").removeClass("hidden")
                        endProcessing();
                        reject();
                        return;
                    } else if (response.errorCode !== 0) {
                        // エラー処理を実装
                        $(".comErrorBox > p").text(errMsg["error.SC_O04_09.00004"])
                        $(".comErrorBox").removeClass("hidden")
                        endProcessing();
                        reject();
                        return;
                    }

                    // SAP CDC APIメソッドのレスポンスからgigyaAssertionを取得
                    var gigyaAssertion = response.gigyaAssertion;
                    localStorage.setItem("gigyaAssertion_" + sessionStorage.getItem("UserId"), gigyaAssertion);

                    // 二要素認証発行
                    sendPassCode(gigyaAssertion).then(() => {
                        resolve();
                    }).catch(() => {
                        reject();
                    });
                };

                // 二要素認証処理初期化で使用するSAP CDC APIメソッドを実行
                window.gigya.accounts.tfa.initTFA({
                    callback: callbackInitTFA, // コールバック関数
                    regToken: localStorage.getItem("regToken_" + sessionStorage.getItem("UserId")), // ログイン処理のコールバック関数で取得した値
                    provider: "gigyaEmail", // 固定値
                    mode: "verify", // 固定値
                });
            });
        };

        // 二要素認証用コード発行
        const sendPassCode = (gigyaAssertion) => {
            return new Promise((resolve, reject) => {
                // 会員情報取得処理
                const callbackGetEmails = (response) => {
                    // メールアドレスID取得処理のエラーチェック
                    if (response.errorCode !== 0) {
                        // エラー処理を実装
                        $(".comErrorBox > p").text(errMsg["error.SC_O04_09.00004"])
                        $(".comErrorBox").removeClass("hidden")
                        endProcessing();
                        reject();
                        return;
                    }

                    // SAP CDC APIメソッドのレスポンスからemailsを取得
                    const emails = response.emails;

                    // emailsに含まれる emailIDを取得
                    var emailID = null;
                    if (emails && Array.isArray(emails) && emails.length > 0 && emails[0] && emails[0].id) {
                        emailID = emails[0].id;
                    }

                    // 二要素認証用コード生成処理
                    const callbackSendVerificationCode = (response) => {
                        // 二要素認証用コード生成処理のエラーチェック
                        if (response.errorCode !== 0) {
                            // エラー処理を実装
                            $(".comErrorBox > p").append(errMsg["error.SC_O04_09.00004"]);
                            $(".comErrorBox").removeClass("hidden");
                            endProcessing();
                            reject();
                            return;
                        }

                        // SAP CDC APIメソッドのレスポンスからphvTokenを取得
                        var phvToken = response.phvToken;
                        localStorage.setItem("phvToken_" + sessionStorage.getItem("UserId"), phvToken);
                        // 正常終了処理を実装
                        resolve();
                    }

                    // 二要素認証用コード生成処理で使用するSAP CDC APIメソッドを実行
                    window.gigya.accounts.tfa.email.sendVerificationCode({
                        callback: callbackSendVerificationCode, // コールバック関数
                        gigyaAssertion: gigyaAssertion,         // 二要素認証処理初期化のコールバック関数で取得した値
                        emailID: emailID,                       // メールアドレスID取得処理のコールバック関数で取得した値
                        lang: "ja",                             // 固定値
                    });

                }

                // メールアドレスID取得処理で使用するSAP CDC APIメソッドを実行
                window.gigya.accounts.tfa.email.getEmails({
                    callback: callbackGetEmails,    // コールバック関数
                    gigyaAssertion: gigyaAssertion, // 二要素認証処理初期化のコールバック関数で取得した値
                });
            });
        };
    })
});
