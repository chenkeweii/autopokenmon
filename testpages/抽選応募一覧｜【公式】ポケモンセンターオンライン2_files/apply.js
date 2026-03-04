/*------------------------------------------------------------
    apply 抽選応募
------------------------------------------------------------*/
$(async function () {

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


    //dayjs設定
    dayjs.extend(dayjs_plugin_utc);
    dayjs.extend(dayjs_plugin_timezone);
    dayjs.locale('ja');

    //抽選申込ステータス
    const applicationStatus = {
        "20": "受付前",
        "30": "受付中",
        "40": "受付完了",
        "50": "受付終了",
    }

    // account JWT 取得
    const getAccountJWT = function () {
        return new Promise((resolve, reject) => {
            window.gigya.accounts.getJWT({
                fields: "UID,email,data.memberID,data.isPhoneNumberVerified",
                callback: (response) => {
                    if (response.errorCode === 0) {
                        resolve(response.id_token)
                    } else {
                        reject(response)
                    }
                }
            })
        })
    }

    const verifySession = function () {
        return new Promise((resolve, reject) => {
            window.gigya.accounts.session.verify({
                callback: function (response) {
                    if (response.errorCode !== 0) {
                        reject(response)
                    } else {
                        resolve(response)
                    }
                }
            })
        })
    }

    let canApplyFlg = true;
    let canCancelFlg = true;
    let applyLotteryGroupId;
    let applyItemPrizeId;
    let cancelLotteryGroupId;
    let jwt;

    const pageInit = async function () {
        let lotteryList;
        jwt = await getAccountJWT();
        try {
            lotteryList = await apiRequest(`${ajaxUrl.getLotteryListUrl}`, 'GET', null, 'json', {"Authorization": "Bearer " + jwt});
        } catch (error) {
            const app = Vue.createApp({
                data() {
                    return {
                        lotteryList: null,
                    }
                }
            })
            const vm = app.mount('.comOrderList');
            // レスポンスのstatusコードが302の場合、dialogを表示する
            if (error && error.type === "opaqueredirect") {
                $("body").removeClass("hidden");
                $("#302_error_dialog").click();
                return;
            }
            // 異常(Http status code=422): 抽選情報が存在しない
            if (error && error.status === 422) {
                const errorJson = await error.json();
                $("#pop03 .title").text(errorJson.message);
                $("body").removeClass("hidden");
                $("#no_dialog").click();
                return;
            } else {
                // その他異常
                try {
                    const errorJson = await error.json();
                    $("#pop04 .title").text(errorJson.message);
                    $("body").removeClass("hidden");
                    $("#error_dialog").click();
                    return;
                } catch (e) {
                    $("#pop04 .title").text(errMsg["errors.unknownError"]);
                    $("body").removeClass("hidden");
                    $("#error_dialog").click();
                    console.error(e);
                    return;
                }
            }
        }
        lotteryList = await lotteryList.json();
        const app = Vue.createApp({
            data() {
                return {
                    lotteryList: lotteryList.data,
                }
            },
            methods: {
                checkboxStatus(lottery) {
                    for (let item of lottery.applicationItems) {
                        if (item.applicationSelectedFlg === "1") {
                            return true;
                        }
                    }
                    return false;
                },
                getApplicationStatus(status) {
                    return applicationStatus[status];
                },
                formatDate(date) {
                    return dayjs(date).tz("Asia/Tokyo")
                        .format('YYYY年 MM月 DD日（ddd） HH時mm分')
                },
                formatMon(mon) {
                    return (mon - 0).toLocaleString();
                },
                clickApply(lotteryGroupId) {
                    applyLotteryGroupId = lotteryGroupId;
                    applyItemPrizeId = $(`.${lotteryGroupId}`).find("input[type='radio']:checked").val();
                },
                clickCancel(lotteryGroupId) {
                    cancelLotteryGroupId = lotteryGroupId;
                },
            }
        });

        const vm = app.mount('.comOrderList');

        $(document).on("click", "dt", function () {
            $(this).toggleClass("on");
            $(this).next("dd").stop().slideToggle(300);
            return false;
        });

        $(document).on("click", "dd .closeLink", function () {
            $(this).toggleClass("on");
            $(this).parent("dd").stop().slideToggle(300);
            $(this).parent("dd").prev('dt').removeClass('on');
            return false;
        });

        $(document).on("click", ".fixPopBox .close02,.fixPopBox .close", function () {
            $(this).parents('.fixPopBox').addClass('none');
            $('body').removeClass('fixed');
            return false;
        });


        const toggleBtnDisabled = function (target, inputStatus) {
            if (!inputStatus) {
                target.find('a[href="#pop01"]').removeClass('on');
                return
            }
            target.find('a[href="#pop01"]').addClass('on');
        };

        const getInputStatus = function (radioName, checkboxName) {
            const radioProp = $(`input[name=${radioName}]:checked`).prop('checked');
            const checkboxProp = $(`input[name=${checkboxName}]`).prop('checked');
            if (!radioProp) return false;
            if (!checkboxProp) return false;
            return true;
        };

        $('.mailForm > form').each(function () {
            let $this = $(this);
            let radioName = $this.find('input[type="radio"]').attr('name');
            let checkboxName = $this.find('input[type="checkbox"]').attr('name');
            let inputStatus = getInputStatus(radioName, checkboxName);
            $this.on('change', function () {
                inputStatus = getInputStatus(radioName, checkboxName);
                toggleBtnDisabled($this, inputStatus);
            });
            toggleBtnDisabled($this, inputStatus);
        });

        // pupup 事件準備
        if ($('.popup-modal').length) {
            var state = false;
            var scrollpos;
            $('.popup-modal').magnificPopup({
                midClick: true,
                mainClass: 'mfp-fade mfp-type',
                removalDelay: 150,
                showCloseBtn: false,
                callbacks: {
                    open: function () {
                        if (state == false) {
                            scrollpos = $(window).scrollTop();
                            $('body').addClass('fixed').css({'top': -scrollpos});
                            state = true;
                        }
                    },
                    close: function () {
                        $('body').removeClass('fixed').css({'top': 0});
                        window.scrollTo(0, scrollpos);
                        $('body').removeClass('fixed');
                        state = false;
                    }
                }
            });

            $('.popup-modal-close').click(function (e) {
                e.preventDefault();
                $.magnificPopup.close();
                return false;
            });
        }

        // 遅延表示
        $(".comBtn01").removeClass("hidden");
        $("body").removeClass("hidden");
    };

    //画面初期化
    pageInit()

    //リロード
    $(".refresh_302").on("click", function (event) {
        event.preventDefault();
        location.reload();
    })

    //マイページリンク
    $(".comBackLink>a").on("click", function (event) {
        event.preventDefault();
        location.href = `${url["ec.site.my.page.url"]}`;
    });

    //抽選のやり方を確認する
    $(".comBtn01 > a").on("click", function (event) {
        event.preventDefault();
        location.href = `${routers.SC_O04_08}`;
    });

    // popup抽選応募
    $("#applyBtn").on("click", async function (event) {
        event.preventDefault();
        if (!canApplyFlg) return;
        canApplyFlg = false;
        try {
            await verifySession();
        } catch (e) {
            canApplyFlg = true;
            // ログインしない場合、ログイン画面に遷移する
            location.href = `${routers.SC_O04_09}?redirect=${encodeURIComponent(location.pathname)}`;
        }

        try {
            jwt = await getAccountJWT();
            await apiRequest(`${ajaxUrl.applyLotteryUrl}`, 'POST', {
                lotteryGroupId: applyLotteryGroupId,
                itemPrizeId: applyItemPrizeId
            }, 'json', {"Authorization": "Bearer " + jwt, "content-type": "application/json;charset=UTF-8"});
            location.reload();
        } catch (error) {
            canApplyFlg = true;
            // レスポンスのstatusコードが302の場合、dialogを表示する
            if (error && error.type === "opaqueredirect") {
                $("body").removeClass("hidden");
                $("#302_error_dialog").click();
                return;
            }
            if (error) {
                try {
                    if (error && error.status === 504){
                        $("#pop04 .title").text(errMsg["error.SC_O04_10.00009"]);
                        $("body").removeClass("hidden");
                        $("#error_dialog").click();
                        return;
                    }
                    const errorJson = await error.json();
                    // セッションタイムアウトまたは権限がない場合
                    if (errorJson.messageId === 'errors.noPermission') {
                        //セットをクリア
                        sessionStorage.clear();
                        // ログインが必要な画面に遷移
                        location.href = `${routers.SC_O04_09}`;
                    } else {
                        $("#pop04 .title").text(errorJson.message);
                        $("#error_dialog").click();
                        return;
                    }
                } catch (e) {
                    $("#pop04 .title").text(errMsg["errors.unknownError"]);
                    $("#error_dialog").click();
                    console.error("システムエーラ:", e);
                    return;
                }
            }
        }
    })

    // popup抽選キャンセル
    $("#cancelBtn").on("click", async function (event) {
        event.preventDefault();
        if (!canCancelFlg) return;
        canCancelFlg = false;
        try {
            await verifySession();
        } catch (e) {
            canCancelFlg = true;
            // ログインしない場合、ログイン画面に遷移する
            location.href = `${routers.SC_O04_09}?redirect=${encodeURIComponent(location.pathname)}`;
        }
        try {
            jwt = await getAccountJWT();
            await apiRequest(`${ajaxUrl.cancelLotteryUrl}`, 'POST', {
                lotteryGroupId: cancelLotteryGroupId,
            }, 'json', {"Authorization": "Bearer " + jwt, "content-type": "application/json;charset=UTF-8"});
            location.reload();
        } catch (error) {
            canCancelFlg = true;
            // レスポンスのstatusコードが302の場合、dialogを表示する
            if (error && error.type === "opaqueredirect") {
                $("body").removeClass("hidden");
                $("#302_error_dialog").click();
                return;
            }
            if (error) {
                try {
                    if (error && error.status === 504){
                        $("#pop04 .title").text(errMsg["error.SC_O04_10.00009"]);
                        $("body").removeClass("hidden");
                        $("#error_dialog").click();
                        return;
                    }
                    const errorJson = await error.json();
                    // セッションタイムアウトまたは権限がない場合
                    if (errorJson.messageId === 'errors.noPermission') {
                        //セットをクリア
                        sessionStorage.clear();
                        // ログインが必要な画面に遷移
                        location.href = `${routers.SC_O04_09}`;
                    } else {
                        $("#pop04 .title").text(errorJson.message);
                        $("#error_dialog").click();
                        return;
                    }
                } catch (e) {
                    $("#pop04 .title").text(errMsg["errors.unknownError"]);
                    $("#error_dialog").click();
                    console.error("システムエーラ:", e);
                    return;
                }
            }
        }
    })
});
