$(function(){
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
})
