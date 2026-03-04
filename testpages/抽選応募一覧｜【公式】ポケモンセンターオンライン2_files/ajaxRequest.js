// ajax非同期のリクエストメソッド (使用Fetch API)
async function apiRequest(url, type, data, dataType, headers = {}) {
    // リクエストオプション
    const fetchOptions = {
        method: type,
        credentials: 'include',
        mode: 'cors',
        headers: {
            ...headers,
            "x-requested-with": "XMLHttpRequest",
            'Access-Control-Allow-Origin': '*'
        },
        // 302リダイレクトを手動で処理
        redirect: 'manual'
    };

    // データがある場合
    if (data) {
        if (type.toLowerCase() === 'get') {
            // GETリクエストの場合、データをURLパラメータに変換
            const params = new URLSearchParams(data).toString();
            url = `${url}${url.includes('?') ? '&' : '?'}${params}`;
        } else {
            // POSTリクエストの場合、データをリクエストボディに変換
            fetchOptions.body = dataType.toLowerCase() === 'json' ?
                JSON.stringify(data) :
                new URLSearchParams(data).toString();
        }
    }

    try {
        const response = await fetch(url, fetchOptions);

        // レスポンスが正常な場合、レスポンスを返す
        if (response.ok) {
            return response;
        }

        // レスポンスが正常でない場合、エラーをスロー、2xx以外の場合
        if (!response.ok) {
            throw response;
        }

    } catch (error) {
        throw error;
    }
}
