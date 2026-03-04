$(function(){
	$('a[href*=\\#]:not([href=\\#],.popup-modal,.popup-btn)').on('click',function() {
	if (location.pathname.replace(/^\//,'') == this.pathname.replace(/^\//,'') && location.hostname == this.hostname) {
			var $target = $(this.hash);
			$target = $target.length && $target || $('[name=' + this.hash.slice(1) +']');
			if ($target.length) {
				if($(this).parents('.menuBox').length){
					setTimeout(function(){
						var targetOffset = $target.offset().top;
						$('html,body').animate({scrollTop: targetOffset}, 1000);
					},100);
				}else{
					var targetOffset = $target.offset().top;
					$('html,body').animate({scrollTop: targetOffset}, 1000);
				}
				return false;
			}
		}
	});

	// テキスト省略
	txtClamp();

	// 1ページに複数カルーセルがあった場合に対応
	if($('.comSlideBox .slideBox').length){
		$('.comSlideBox .slideBox').each(function(){
			let $this = $(this);
			let perwidth = $this.find('.photoList li').innerWidth();
			if ($this.find('.photoList .item').length) {
				perwidth = $this.find('.photoList .item').innerWidth();
			}
			let shownum = $this.find('.photoList').innerWidth() / perwidth;
			$this.find('.photoList a').matchHeight();
			$this.find('.photoList').slick({
				infinite: false,
				centerMode: false,
				slidesToScroll: 1,
				dots: false, 
				autoplay: false,
				fade: false,
				variableWidth: true,
				arrows: true,
				pauseOnHover: false,
				pauseOnFocus:false,
				lazyLoad: 'ondemand',
				slidesToShow: shownum,
				nextArrow: $this.find('.arrowList li.next'),
				prevArrow: $this.find('.arrowList li.prev'),
				responsive: [
					{
						breakpoint: 519,
						settings: {
						}
					}
				],
			});
			setTimeout(function(){
				$this.find('.photoList a').matchHeight();
			},100);
		})
	};

	if($('.comTagBox .checkDl').length){
		// ラジオボタン初期化
		setTimeout(function(){
			$('.comTagBox .checkDl input[type=radio]:checked').prop('checked',false);
		},10);

		const isSelList = $('.comTagBox .selList').length ? 1 : 0;
        $('.comTagBox .checkDl input').on('change',function(){
            if($('.comTagBox .checkDl input:checked').length){
				$('.comTagBox .rBox .js-cartBtn').removeClass('default');
                if(isSelList) $('.comTagBox .selList').slideDown();
            }else{
				$('.comTagBox .rBox .js-cartBtn').addClass('default');
                if(isSelList) $('.comTagBox .selList').slideUp();
            }
        });
    }

    if($('.comTagBox .btn.limitBtn').length){
        $('.comTagBox .btn.limitBtn').each(function(){
            let $this = $(this);
            // $this.parents('.comTagBox').find('.only').hide();
            let num = $(this).data('limit')?parseInt( $(this).data('limit')):0;
            let select = $(this).parents('.comTagBox').find('.numList select');
            select.on('change',function(){
                if(num != 0 && parseInt(select.val()) > num){
                    $this.addClass('notallowed');
                }else{
                    $this.removeClass('notallowed');
                }
            }).trigger('change');
            $this.on('click',function(){
                if($this.hasClass('notallowed')){
                    $this.parents('.comTagBox').find('.only').show();
                }else{
                    $this.parents('.comTagBox').find('.only').hide();
                }
            })
        })
    }

	$('#gNavi .linkUl .openmenu').on('click',function(){
		if(window.innerWidth > 1039){
			$('.menuBox').addClass('open');
			$('.cover').fadeIn();
		}
		return false;
	});

	$('.menuBox .close,.cover').on('click',function(){
		if(window.innerWidth <= 1039){
			$('.menuBox .innerBox').show();
			$('.menuBox .linkBox').hide();
		}
		$('.menuBox').removeClass('open');
		$('.cover').fadeOut();
	});

	$('.menuBox .linkBox .linkList > li > a').on('click',function(){
		if($(this).next('.subList').length){
			$(this).toggleClass('on');
			$(this).next('.subList').slideToggle();
			return false;
		}
	});

	$('#gHeader .menu').on('click',function(){
		$('.menuBox').addClass('open');
		$('#gHeader .searchBox').removeClass('open');
	});

	$('.menuBox .innerBox .linkList > li.list01 a').on('click',function(){
		$('.menuBox .innerBox').hide();
		$('.menuBox .linkBox').show();
		return false;
	});

	$('.menuBox .linkBox .title a').on('click',function(){
		if(window.innerWidth <= 1039){
			$('.menuBox .innerBox').show();
			$('.menuBox .linkBox').hide();
		}
		return false;
	});

	$('#gHeader .search').on('click',function(){
		$('.menuBox .innerBox').show();
		$('.menuBox .linkBox').hide();
		$('.menuBox').removeClass('open');
		$('#gHeader .searchBox').toggleClass('open');
		$('#gHeader .searchBox').removeClass('is_suggest');
		$('#gHeader .searchBox .resultsBox').hide();
	})

	if($('.comPriceList').length){
        $('.comPriceList li').each(function(){
            let $this = $(this);
            let star = $this.find('.star');
            let del = $this.find('.rBox a');
            star.on('click',function(){
                $(this).toggleClass('on');
            });
            del.on('click',function(){
                $this.hide();
                return false;
            })
        });
    }

	if($('.comItemBox').length){
		$(window).on('resize',function(){
			if(window.innerWidth > 519){
				$('.comTagBox .rBox').insertBefore($('.comTagBox .lBox'));
			}else{
				$('.comTagBox .rBox').insertAfter($('.comTagBox .lBox'));
			}}
		).trigger('resize');
	}

	if($('.comTagBox .linkList').length){
        $('.comTagBox .linkList').each(function(){
            let $this = $(this);
            let star = $this.find('.js-star');
            star.on('click',function(){
				if ($(this).hasClass('on')) {
					$(this).find('.txt').text('お気に入りに追加する');
				} else {
					$(this).find('.txt').text('お気に入りに追加済み');
				}
                $(this).toggleClass('on');
            });
        });
    }

	if($('.popup-modal').length){
		var state = false;
		var scrollpos;
		$('.popup-modal').magnificPopup({
			midClick: true,
			mainClass: 'mfp-fade mfp-type',
			removalDelay: 150,
			showCloseBtn: false,
			callbacks: {
				open: function() {
					if(state == false) {
						scrollpos = $(window).scrollTop();
						$('body').addClass('fixed').css({'top': -scrollpos});
						state = true;
					}
				},
				close: function(){
					$('body').removeClass('fixed').css({'top': 0});
					window.scrollTo( 0 , scrollpos );
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
	
	if($('.mailForm .radioList li').length){
		$('.mailForm .radioList li input').on('change',function(){
			$('.mailForm .radioList li input').each(function(){
				if($(this).prop('checked')){
					$(this).parents('.radio').next('.subBox').show();
				}else{
					$(this).parents('.radio').next('.subBox').hide();
				}
			})
		}).trigger('change');
	}
	if($('.mailForm .radioList .subBox .check').length){
		$('.mailForm .radioList .subBox .check input').on('change',function(){
			$('.mailForm .radioList .subBox .check input').each(function(){
				if($(this).prop('checked')){
					$(this).parents('.check').next('.checkBox').show();
				}else{
					$(this).parents('.check').next('.checkBox').hide();
				}
			})
		}).trigger('change');
	}

	if($('.comInfoBox .infoDl').length){
		$('.comInfoBox .infoDl dt').click(function(){
			$(this).toggleClass('on');
			$(this).next().stop().slideToggle();
		});
	}

	if($('.mailForm .formList dt a').length){
		$('.mailForm .formList dt a').on('click',function(){
			if(window.innerWidth < 519){
				$(this).toggleClass('on');
			}
			return false;
		})
		$('body').on('click',function(e){
			if(window.innerWidth < 519 && !$(e.target).parents('.hoverBox').length && $('.mailForm .formList dt a').hasClass('on')){
				$('.mailForm .formList dt a').removeClass('on');
			}
		})
	}

	if($('.mailForm .formList dt .hoverInner').length){
		$('.mailForm .formList dt .hoverInner').on('click',function(){
			if(window.innerWidth < 519){
				$(this).toggleClass('on');
			}
			return false;
		})
		$('body').on('click',function(e){
			if(window.innerWidth < 519 && !$(e.target).parents('.hoverBox').length && $('.mailForm .formList dt .hoverInner').hasClass('on')){
				$('.mailForm .formList dt .hoverInner').removeClass('on');
			}
		})
	}

	if($('.comTextBox .link a').length){
		$('.comTextBox .link a').on('click',function(){
			if(window.innerWidth < 519){
				$(this).toggleClass('on');
			}
			return false;
		})
		$('body').on('click',function(e){
			if(window.innerWidth < 519 && !$(e.target).parents('.hoverBox').length && $('.comTextBox .link a').hasClass('on')){
				$('.comTextBox .link a').removeClass('on');
			}
		})
	}

	if($('.comjsnum').length){
		$('.comjsnum').each(function(){
			var flag = true;
			$(this).on("compositionstart", function () {
				flag = false;
			});
			$(this).on("compositionend", function () {
				flag = true;
			});
			$(this).on('input',function(){
				let $this = $(this);
				setTimeout(function(){
					if (flag) {
						let letter = $this.val();
						var filteredValue = letter.replace(/[^0-9]/g, '');
						$this.val(filteredValue);
					}
				},10);
			});
		});
    }

	if($('.comjsdate').length){
		$('.comjsdate').each(function(){
			var flag = true;
			$(this).on("compositionstart", function () {
				flag = false;
			});
			$(this).on("compositionend", function () {
				flag = true;
			});
			$(this).on('input',function(){
				let $this = $(this);
				setTimeout(function(){
					if (flag) {
						let letter = $this.val();
						var filteredValue = letter.replace(/[^0-9\/]/g, '');
						$this.val(filteredValue);
					}
				},10);
			});
		})
        $('.comjsdate').on('blur',function(){
            let letter = $(this).val();
            let num = letter.indexOf('/');
            if(num == -1){
                let letter01 = letter.slice(0, 2);
                let letter02 = letter.slice(2, 4);
                let newletter = letter01+'/'+letter02;
                $(this).val(newletter);
            }else{
                if(num != 2){
                    letter = letter.replace(/\//g, "");
                    let letter01 = letter.slice(0, 2);
                    let letter02 = letter.slice(2, 4);
                    let newletter = letter01+'/'+letter02;
                    $(this).val(newletter);
                }
            }
			if(letter === ""){ //何も入力されていない場合にスラッシュが残るのを防ぐ
				$(this).val("");
			}
        });
    }


	// 20240426 parents()→parent()に修正
	$('.accordion .accTitle').on('click', function() {
		$(this).parent().toggleClass("open");
		$(this).toggleClass("on");
		$(this).next(".accCont").stop().slideToggle(300);
		return false;
	});
	$('.accordion .subAccTtl').on('click', function() {
		$(this).toggleClass("on");
		$(this).next(".subAccList").stop().slideToggle(300);
		return false;
	});


	if($('.comfilterJs').length){
		$('.popBox .narrowBox .selectList01 select').eq(0).on('change',function(){
			if($(this).val() == ''){
				$('.popBox .narrowBox .selectList01 select').eq(1).attr('disabled',true);
			}else{
				$('.popBox .narrowBox .selectList01 select').eq(1).attr('disabled',false);
			}
		}).trigger('change');

		$('.popBox .narrowBox .subAccList input').on('change',function(){
			let html = '';
			$('.popBox .narrowBox .subAccList input:checked').each(function(){
				let text = $(this).val();
				// カテゴリ選択解除ボタン追加
				html += '<li>'+text+'<div class="clear js-delCategory"><img src="/images/common/close01.png" alt="close"></div></li>';
				// 選択カテゴリ解除処理
				$('.popBox .narrowBox .checkResult').on('click', '.js-delCategory', function() {
					$('*[name=selectCat]').prop('checked', false).trigger('change');
				});
			});
			$('.popBox .narrowBox .checkResult').html(html);
			// 20240426 カテゴリ選択時にプルダウン閉じる仕様へ変更
			$('.popBox .narrowBox .accordion').removeClass('open');
			$('.popBox .narrowBox .accTitle').removeClass('on');
			$('.popBox .narrowBox .subAccTtl').removeClass('on');
			$('.popBox .narrowBox .accCont').stop().slideUp();
			$('.popBox .narrowBox .subAccList').stop().slideUp();
		}).trigger('change');

		$('.popBox input[type="reset"]').on('click',function(){
			$('.popBox .narrowBox .selectList01 select').val('').trigger('change');
			$('.popBox .mailForm .formList input[type="text"]').val('');
			$('.popBox .mailForm .formList input[type="radio"]').prop('checked',false).trigger('change');
			$('.popBox .mailForm .formList input[type="checkbox"]').prop('checked',false).trigger('change');
			return false;
		});
	}

	if($('.comShopBox').length && $('.comShopBox .slideBox .photoList li').length){
		let imgsrc = $('.comShopBox .slideBox .photoList li > img').eq(0).attr('src');
		$('.comShopBox').css('background-image','url('+imgsrc+')');
		let num = $('.comShopBox .phoUl li').length;
		let slick_center = 0;
		if(num > 5){
			$('.comShopBox .phoUl').slick({
				slidesToShow: 5,
				arrows: false,
				focusOnSelect: true,
				focusOnChange: true,
				asNavFor: $('.comShopBox .slideBox .photoList'),
			});
			$('.comShopBox .slideBox .photoList').slick({
				prevArrow: '.comShopBox .slideBox .arrowList li.prev',
				nextArrow: '.comShopBox .slideBox .arrowList li.next',
				centerMode: true,
                variableWidth: true,
				asNavFor: $('.comShopBox .phoUl'),
			});
			$('.comShopBox .slideBox .photoList').on('beforeChange', function(event, slick, currentSlide, nextSlide){
				slick_center = nextSlide;
			});
		}else{
			$('.comShopBox .slideBox .photoList').slick({
				prevArrow: '.comShopBox .slideBox .arrowList li.prev',
				nextArrow: '.comShopBox .slideBox .arrowList li.next',
				centerMode: true,
                variableWidth: true,
			});
			$('.comShopBox .slideBox .photoList').on('beforeChange', function(event, slick, currentSlide, nextSlide){
				slick_center = nextSlide;
				$('.comShopBox .phoUl li').removeClass('on').eq(nextSlide).addClass('on');
			});
			$('.comShopBox .phoUl li').on('click',function(){
				let num = $(this).index();
				$('.comShopBox .slideBox .photoList').slick('slickGoTo',num);
			});
		}
		$('.comShopBox').addClass('setSlide');

		$('.popBox02 .pageBox .all').text(num);
		$('.popBox02 .flexBox .rBox .photoList').slick({
			arrows: false,
		});

		$('.popBox02 .flexBox .lBox .phoList li').eq(0).addClass('on');
			$('.popBox02 .flexBox .rBox .photoList').on('beforeChange', function(event, slick, currentSlide, nextSlide){
				slick_center = nextSlide;
				$('.popBox02 .pageBox .page').text(nextSlide+1);
				$('.popBox02 .flexBox .lBox .phoList li').removeClass('on').eq(nextSlide).addClass('on');
			});

		$('.popBox02 .flexBox .lBox .phoList li').on('click',function(){
			let ind = $(this).index();
			$('.popBox02 .flexBox .rBox .photoList').slick('slickGoTo',ind);
		});

		var state = false;
		var scrollpos;
		$('.popup-btn').magnificPopup({
			midClick: true,
			mainClass: 'mfp-fade mfp-type',
			removalDelay: 150,
			showCloseBtn: false,
			callbacks: {
				open: function() {
					if(state == false) {
						scrollpos = $(window).scrollTop();
						$('body').addClass('fixed').css({'top': -scrollpos});
						state = true;
						$('.popBox02 .flexBox .rBox .photoList').slick('setPosition');
						$('.popBox02 .flexBox .rBox .photoList').slick('slickGoTo',slick_center);
					}
				},
				close: function(){
					$('body').removeClass('fixed').css({'top': 0});
					window.scrollTo( 0 , scrollpos );
					$('body').removeClass('fixed');
					$('.comShopBox .slideBox .photoList').slick('slickGoTo',slick_center);
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

	if($('.comTagBox .numList').length){
		$('.comTagBox .numList').each(function(){
			let reduce = $(this).find('.reduce');
			let add = $(this).find('.add');
			let select = $(this).find('.num select');
			select.on('change',function(){
				add.removeClass('default');
				reduce.removeClass('default');
				if(select.val() == 1){
					reduce.addClass('default');
				}
				if(select.val() == 10){
					add.addClass('default');
				}
			}).trigger('change');
			reduce.on('click',function(){
				let new_val = parseInt(select.val())-1;
				if(new_val < 1){
					new_val = 1;
				}
				select.val(new_val).trigger('change');
				return false;
			});
			add.on('click',function(){
				let new_val = parseInt(select.val())+1;
				if(new_val > 10){
					new_val = 10;
				}
				select.val(new_val).trigger('change');
				return false;
			});
		});
	}

	if($('.comInfoBox .infoDl .slideBox').length){
		$('.comInfoBox .infoDl .slideBox').each(function(){
			let nextA = $(this).find('.arrowList .next');
			let prevA = $(this).find('.arrowList .prev');
			$(this).find('.photoList').slick({
                infinite: false,
                prevArrow: prevA,
                nextArrow: nextA,
                slidesToShow: 5,
                variableWidth: true,
				responsive: [
					{
						breakpoint: 519,
						settings: {
							slidesToShow: 1,
						}
					}
				],
			})
		})
	}

	if($('.comSlideBox.goods .bgList').length) {
		$('.comSlideBox.goods .bgList').slick({
			fade: true,
			arrows: false,
			speed: 5000,
			autoplay: true,
			autoplaySpeed: 0,
		}).on('touchend',function(){
			$(this).slick('slickPlay');
		})
	}

	if($('.comSlideBox.newlyGoods .bgList').length) {
		$('.comSlideBox.newlyGoods .bgList').slick({
			fade: true,
			arrows: false,
			speed: 5000,
			autoplay: true,
			autoplaySpeed: 0,
		}).on('touchend',function(){
			$(this).slick('slickPlay');
		})
	}

	$('.comTabPanel .tabBox').hide();
	$('.comTabPanel .tabBox').eq(0).show();

	$('.comTabPanel .tabUl li a').click(function(){
		var ind=$(this).parent('li').index();
		$(this).parent('li').addClass('on').siblings().removeClass('on');
		$('.tabBox').hide();
		$('.tabBox:eq('+ind+')').show();
		return false;
	});

	if($('.notify_box').length) {
		$('body').addClass('is_notify');
	}

	$('.notify_box .close').on('click',function(){
		$(this).parents('.notify_box').slideUp();
		$('body').removeClass('is_notify');
	});

// 下記記載の各種js処理を上述内の任意タイミングで実行できるようmerge（20240610）
	// 検索欄の入力内容クリア
	$('.js-clear').on('click',function(){
		$('*[name=search01]').val('');
		if($('#gHeader .searchBox .resultsBox').length){
			$(this).parent().find('.resultsBox').hide();
			$(this).parents('.searchBox').removeClass('is_suggest');
		}
	})

	// 複数行の省略処理（data-trim-length属性で文字数指定可、ない場合は36文字）
	function txtClamp() {
		if($('.js-txtClamp').length) {
			$('.js-txtClamp').each(function() {
				var txt = $(this).text();
				var trimCount = $(this).data('trim-length') ?? 36;
				if (trimCount && txt.length >= trimCount) {
					$(this).text(txt.substring(0, (trimCount - 1)) + '...');
				}
			});
		}
	}

	// アコーディオン汎用処理
	$('.js-accordion > .js-accordion-toggle').on('click',function() {
		if($(this).next('.js-accordion-item').length){
			$(this).toggleClass('on');
			$(this).next('.js-accordion-item').slideToggle();
			return false;
		}
	});

	// パスワード表示切替処理
	$('.js-togglePwShow').on('click',function() {
		var inputPw = $(this).prev();
		if (!$(this).hasClass('is_show')) {
			inputPw.attr('type', 'text');
		} else {
			inputPw.attr('type', 'password');
		}
		$(this).toggleClass('is_show');
	})

	// 端末標準の共有機能呼び出し処理
	$('.js-share').on('click',async function() {
		try {
			await navigator.share({
				title: document.title,
				url: location.href
			});
		} catch (error) {
			console.error(error);
		}
	})

	// jsバリデーション汎用処理
	$('.js-validate').on('input',function() {
		let replaceVal = $(this).val();
		// 数値入力の場合、半角数字以外をvalueから除外する
		if (
			$(this).hasClass('playerId') ||
			$(this).hasClass('telNumber') ||
			$(this).hasClass('postalCode') ||
			$(this).hasClass('authCode') ||
			$(this).hasClass('orderNumber') ||
			$(this).hasClass('itemCode') ||
			$(this).hasClass('commonNum')
		) {
			replaceVal = replaceVal.replace(/[^0-9]/g, '');
		}
		// removeSignクラス付与の場合、記号を除外
		// TODO 20240621現在未使用、不要なら要削除
		if ($(this).hasClass('removeSign')) {
			replaceVal = replaceVal.replace(/[【】『』，．・；’「」｀＼,\.~!@#\$%\^&\*\(\)_\+\-=\{\}\[\]:;"'<>?\\\/\|]/g, '');
		}
		// half2fullクラス付与の場合、半角→全角変換
		// TODO 20240621現在未使用、不要なら要削除
		if ($(this).hasClass('half2full')) {
			replaceVal = half2full(replaceVal);
		}
		switch(true){
			// プレイヤーID
			case ($(this).hasClass('playerId')) :
				if (replaceVal.length > 10) {
					replaceVal = replaceVal.slice(0, 10);
				}
				$(this).val(replaceVal);
				break;

			// 電話番号
			case ($(this).hasClass('telNumber')) :
				if (replaceVal.length > 11) {
					replaceVal = replaceVal.slice(0, 11);
				}
				$(this).val(replaceVal);
				break;

			// 郵便番号
			case ($(this).hasClass('postalCode')) :
				if (replaceVal.length > 7) {
					replaceVal = replaceVal.slice(0, 7);
				}
				$(this).val(replaceVal);
				break;

			// 認証コード
			case ($(this).hasClass('authCode')) :
				if (replaceVal.length > 6) {
					replaceVal = replaceVal.slice(0, 6);
				}
				$(this).val(replaceVal);
				break;

			// 注文番号
			case ($(this).hasClass('orderNumber')) :
				if (replaceVal.length > 13) {
					replaceVal = replaceVal.slice(0, 13);
				}
				$(this).val(replaceVal);
				break;

			// 商品コード
			case ($(this).hasClass('itemCode')) :
				if (replaceVal.length > 13) {
					replaceVal = replaceVal.slice(0, 13);
				}
				$(this).val(replaceVal);
				break;

			// 数字入力汎用処理
			case ($(this).hasClass('commonNum')) :
				$(this).val(replaceVal);
				break;

			// ニックネーム
			case ($(this).hasClass('nickName')) :
				if (replaceVal.length > 12) {
					replaceVal = replaceVal.slice(0, 12);
				}
				$(this).val(replaceVal);
				break;
		}
	})

	// 半角→全角変換処理（英数カナのみ）
	// TODO 20240621現在未使用、不要なら要削除
	function half2full(target) {
		// カナ変換表
		const kanaMap = {
			'ｶﾞ': 'ガ', 'ｷﾞ': 'ギ', 'ｸﾞ': 'グ', 'ｹﾞ': 'ゲ', 'ｺﾞ': 'ゴ',
			'ｻﾞ': 'ザ', 'ｼﾞ': 'ジ', 'ｽﾞ': 'ズ', 'ｾﾞ': 'ゼ', 'ｿﾞ': 'ゾ',
			'ﾀﾞ': 'ダ', 'ﾁﾞ': 'ヂ', 'ﾂﾞ': 'ヅ', 'ﾃﾞ': 'デ', 'ﾄﾞ': 'ド',
			'ﾊﾞ': 'バ', 'ﾋﾞ': 'ビ', 'ﾌﾞ': 'ブ', 'ﾍﾞ': 'ベ', 'ﾎﾞ': 'ボ',
			'ﾊﾟ': 'パ', 'ﾋﾟ': 'ピ', 'ﾌﾟ': 'プ', 'ﾍﾟ': 'ペ', 'ﾎﾟ': 'ポ',
			'ｳﾞ': 'ヴ', 'ﾜﾞ': 'ヷ', 'ｦﾞ': 'ヺ',
			'ｱ': 'ア', 'ｲ': 'イ', 'ｳ': 'ウ', 'ｴ': 'エ', 'ｵ': 'オ',
			'ｶ': 'カ', 'ｷ': 'キ', 'ｸ': 'ク', 'ｹ': 'ケ', 'ｺ': 'コ',
			'ｻ': 'サ', 'ｼ': 'シ', 'ｽ': 'ス', 'ｾ': 'セ', 'ｿ': 'ソ',
			'ﾀ': 'タ', 'ﾁ': 'チ', 'ﾂ': 'ツ', 'ﾃ': 'テ', 'ﾄ': 'ト',
			'ﾅ': 'ナ', 'ﾆ': 'ニ', 'ﾇ': 'ヌ', 'ﾈ': 'ネ', 'ﾉ': 'ノ',
			'ﾊ': 'ハ', 'ﾋ': 'ヒ', 'ﾌ': 'フ', 'ﾍ': 'ヘ', 'ﾎ': 'ホ',
			'ﾏ': 'マ', 'ﾐ': 'ミ', 'ﾑ': 'ム', 'ﾒ': 'メ', 'ﾓ': 'モ',
			'ﾔ': 'ヤ', 'ﾕ': 'ユ', 'ﾖ': 'ヨ',
			'ﾗ': 'ラ', 'ﾘ': 'リ', 'ﾙ': 'ル', 'ﾚ': 'レ', 'ﾛ': 'ロ',
			'ﾜ': 'ワ', 'ｦ': 'ヲ', 'ﾝ': 'ン',
			'ｧ': 'ァ', 'ｨ': 'ィ', 'ｩ': 'ゥ', 'ｪ': 'ェ', 'ｫ': 'ォ',
			'ｯ': 'ッ', 'ｬ': 'ャ', 'ｭ': 'ュ', 'ｮ': 'ョ',
		}
		// 英数字変換
		let replaceStr = target.replace(/[A-Za-z0-9]/g, function(el) {
			return String.fromCharCode(el.charCodeAt(0) + 0xFEE0);
		});
		// カナ変換
		let reg = new RegExp('(' + Object.keys(kanaMap).join('|') + ')', 'g');
		return replaceStr
			.replace(reg, function (match) {
				return kanaMap[match];
			})
			.replace(/ﾞ/g, '゛')
			.replace(/ﾟ/g, '゜');
	}

	// 絞り込み項目解除処理
	$('.js-delFilter').on('click',function(){
		$(this).parent('li').remove();
		return false;
	});

	// ページング処理（拡張の可能性があるため関数化）
	function pagination() {
		// 初期化
		let params = new URLSearchParams(window.location.search);
		let pageNum = parseInt(params.get('page')) || 1;
		const allOptVal = $('[name=page] option').map(function() {
			return parseInt($(this).val());
		}).get();
		if (pageNum && $.inArray(pageNum, allOptVal) > -1) {
			$('[name=page]').val(pageNum);
			if (pageNum == allOptVal[0]) {
				$('.js-paging .pageNavi .prev').addClass('disabled');
			}
			if (pageNum == allOptVal[allOptVal.length - 1]) {
				$('.js-paging .pageNavi .next').addClass('disabled');
			}
		}
		// ページ番号が切り替わったときsubmit
		$('.js-paging [name=page]').on('change',function() {
			$('.js-paging').submit();
		})

		// 左右アロー押下時submit（パラメータ変更してリロード）
		$('.js-paging .pageNavi .prev').on('click',function() {
			params.set('page', --pageNum);
			window.location.search = params.toString();
		})
		$('.js-paging .pageNavi .next').on('click',function() {
			params.set('page', ++pageNum);
			window.location.search = params.toString();
		})
	}
	pagination();

	if($('#gHeader .searchBox .resultsBox').length){
        $('#gHeader .searchBox [name="search01"]').on({
			'input': function() {
				if($(this).val() == ''){
					$(this).parent().find('.resultsBox').hide();
					$(this).parents('.searchBox').removeClass('is_suggest');
				}else{
					$(this).parent().find('.resultsBox').show();
					$(this).parents('.searchBox').addClass('is_suggest');
				}
			},
			'click': function() {
				if($(this).parent().find('.resultsBox').css('display') != 'none'){
					$(this).parent().find('.resultsBox').hide();
					$(this).parents('.searchBox').removeClass('is_suggest');
				}
			}
		});
		$('#gHeader .searchBox .resultsBox a').on('click',function(){
			var txt = $(this).text();
			$(this).parents('.searchBox').find('[name="search01"]').val(txt);
			$(this).parents('.resultsBox').hide();
			$(this).parents('.searchBox').removeClass('is_suggest');
			return false;
		});

		$('#gHeader .innerBox.pc .searchBox [name="search01"]').on('focusout', function(){
			let $this = $(this);
			setTimeout(function(){
				$this.parent().find('.resultsBox').hide();
				$(this).parents('.searchBox').removeClass('is_suggest');
			},100);
		});

		$('#gHeader .searchBox.sp .close').on('click',function(){
			$(this).parents('.resultsBox').hide();
			$(this).parents('.searchBox').removeClass('open');
			$(this).parents('.searchBox').removeClass('is_suggest');
		});
	}


	if($('.comSlideBox01 .slideUl').length){
		$('.comSlideBox01 .slideUl').slick({
			centerMode: true,
			centerPadding: '0',
			slidesToShow: 1,
			slidesToScroll: 1,
			arrows: true,
			dots: true,
			pauseOnHover: false,
			pauseOnFocus: false,
			autoplay: true,
			appendDots: '.slick-dots',
			responsive: [
				{
					breakpoint: 897,
					settings: {
						slidesToShow: 1,
					}
				}
			],
		});
	
		$('.comSlideBox01 .slideUl').on('touchstart', function(){
			$('.comSlideBox01 .slideUl').slick('slickPlay');
		});
	}
});

$(window).on('load',function(){
	$(window).trigger('resize');
	var localLink = window.location+'';
	if(localLink.indexOf("#") != -1 && localLink.slice(-1) != '#'){
		localLink = localLink.slice(localLink.indexOf("#")+1);
		if($('#'+localLink).length){
			setTimeout(function(){
				$('html,body').animate({scrollTop: $('#'+localLink).offset().top}, 500);
			},100);
		}
	}
});

// 同じく競合を避けるために最下部に追加（2024/04/18）
function sliceMaxLength(elem, maxLength) {
	elem.value = elem.value.slice(0, maxLength);
}

function moveNextFeild(str, maxLength){
	if(str.value.length >= maxLength){
		$(str).nextAll('input').focus();
	}
}
