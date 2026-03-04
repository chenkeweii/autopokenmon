window.__gigyaConf = {
    onGigyaServiceReady: function () {
        const routes = () => {
            if (needAuthView.includes(location.pathname)) {
                window.gigya.accounts.session.verify({
                    callback: function (response) {
                        if (response.errorCode !== 0) {
                            // ログインしない場合、ログイン画面に遷移する
                            const redirectPath = location.pathname + location.search + location.hash;
                            location.href =`${routers.SC_O04_09}?redirect=${encodeURIComponent(redirectPath)}`;
                        }
                    }
                });
            }
        }
        routes();
    }
};


