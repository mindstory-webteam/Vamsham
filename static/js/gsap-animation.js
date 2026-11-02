gsap.registerPlugin(ScrollTrigger, SplitText);
gsap.config({
    nullTargetWarn: false,
    trialWarn: false
});
/*----  Functions  ----*/

//** Image animation **//
function pbmit_img_animation() {
	const boxes = gsap.utils.toArray('.pbmit-animation-style1,.pbmit-animation-style2,.pbmit-animation-style3,.pbmit-animation-style4,.pbmit-animation-style5,.pbmit-animation-style6,.pbmit-animation-style7');
	boxes.forEach(img => {
		gsap.to(img, {
			scrollTrigger: {
				trigger: img,
				start: "top 70%",
				end: "bottom bottom",
				toggleClass: "active",
				once: true,
			}
		});
	});
}

function getpercentage(x, y, elm) {
	elm.find('.pbmit-fid-inner').html(y + '/' + x);
	var cal = Math.round((y * 100) / x);
	return cal;
}

//** Title animation **//
function pbmit_title_animation() {
	ScrollTrigger.matchMedia({
		"(min-width: 1025px)": function() {
			var pbmit_var = jQuery('.pbmit-heading, .pbmit-heading-subheading');
			if (!pbmit_var.length) {
				return;
			}
			const quotes = document.querySelectorAll(".pbmit-heading .pbmit-title , .pbmit-heading-subheading .pbmit-title");
			quotes.forEach(quote => {
				var getclass = quote.closest('.pbmit-heading ,.pbmit-heading-subheading').className;
				var animation = getclass.split('animation-');
				if (animation[1] == "style4") return
				//Reset if needed
				if (quote.animation) {
					quote.animation.progress(1).kill();
					quote.split.revert();
				}
				quote.split = new SplitText(quote, {
					type: "lines,words,chars",
					linesClass: "split-line"
				});
				gsap.set(quote, { perspective: 400 });
				if (animation[1] == "style1") {
					gsap.set(quote.split.chars, {
						opacity: 0,
						y: "90%",
						rotateX: "-40deg"
					});
				}
				if (animation[1] == "style2") {
					gsap.set(quote.split.chars, {
						opacity: 0,
						x: "50"
					});
				}
				if (animation[1] == "style3") {
					gsap.set(quote.split.chars, {
						opacity: 0,
					});
				}
				quote.animation = gsap.to(quote.split.chars, {
				scrollTrigger: {
					trigger: quote,
					start: "top 90%",
				},
				x: "0",
				y: "0",
				rotateX: "0",
				opacity: 1,
				duration: 1,
				ease: Back.easeOut,
				stagger: .02
				});
			});
		},
	});
}

function pbmit_sticky() {
	ScrollTrigger.matchMedia({
		"(min-width: 1200px)": function() {
			let pbmit_sticky_container = jQuery(".pbmit-sticky-col");
			let section = pbmit_sticky_container.closest('.section');
			if (!section[0]) {
				section = pbmit_sticky_container.closest('.pbmit-sticky-section');
			} 
			let tl = gsap.timeline({
				scrollTrigger: {
					pin: pbmit_sticky_container,
					scrub: 1,
					start: "top top", 
					trigger: section,
					end: () => "+=" + ((section.height() + 300) - window.innerHeight), 
					invalidateOnRefresh: true
				},
				defaults: { ease: "none", duration: 1 }
			});
		},
	}); 
}

var pbmit_thia_sticky = function() {
	if(typeof jQuery.fn.theiaStickySidebar == "function"){
		jQuery('.pbmit-sticky-sidebar').theiaStickySidebar({
			additionalMarginTop: 100
		});
		jQuery('.pbmit-sticky-column').theiaStickySidebar({
			additionalMarginTop: 120
		});
	}
}

function pbmit_sticky_special() {
	if (jQuery('.pbmit-sticky-col2-special').hasClass('.elementor-element-edit-mode')) {
		return;
	}
	ScrollTrigger.matchMedia({
		"(min-width: 1024px)": function() { 
			let pbmit_sticky_2 = jQuery(".pbmit-sticky-col2-special");
			let section = jQuery('.pbmit-sticky-special'); 
			let section_height = pbmit_sticky_2.height();
			const tweenOne = gsap.to(pbmit_sticky_2, {
				y: - (section_height - 650),
				scrollTrigger: {
				  trigger: section,
				  pin: section,
				  scrub:1,
				  scrub: true,
				  start: "top top+=0px",
				  end: () => '+=' + (section_height - 0),				
				}
			}); 
		},
		"(max-width:1024px)": function() {
			ScrollTrigger.getAll().forEach(section => section.kill(true));
		}
	}); 
}

function pbmit_extend_section() {
	const pbmit_elm = gsap.utils.toArray('.pbmit-textimonial-bg-move');
	if (pbmit_elm.length == 0) return
	ScrollTrigger.matchMedia({
		"(min-width: 1025px)": function() {
			pbmit_elm.forEach((box, i) => {
				let tl = gsap.timeline({
					scrollTrigger: {
						trigger: box,
						start: "top 80%",
						end: "+=700px",
						scrub: 1
					},
					defaults: { ease: "none" }
				});
				tl.fromTo(box, { clipPath: 'inset(0% 7% 0% 7% round 30px)' }, { clipPath: 'inset(0% 0% 0% 0% round 0px)', duration: 3 }) 
			});
		},
		"(max-width:1024px)": function() {
			ScrollTrigger.getAll().forEach(pbmit_elm => pbmit_elm.kill(true));
		}
	});
}

function pbmit_testimonial_review() {
	jQuery(".pbmit-element-testimonial-style-2").each(function() {
		if (typeof Swiper !== 'undefined') {

			var pbmit_blockquote = new Swiper('.pbmit-gallery-top', {
				spaceBetween: 0,
				loop:true,
				loopedSlides: 6, //looped slides should be the same
				centeredSlides: true,
				autoplay: {
					delay: 5000,
					disableOnInteraction: false,
				},
				navigation: {
				nextEl: '.swiper-button-next',
				prevEl: '.swiper-button-prev',
				},
			});
			var pbmit_thumb = new Swiper('.pbmit-gallery-thumbs', {
				spaceBetween: 0,
				loop: true,
				slidesPerView: 5,
				loopedSlides: 6, //looped slides should be the same
				slideToClickedSlide: true,
				centeredSlides: true,
			});
			pbmit_blockquote.controller.control = pbmit_thumb;
			pbmit_thumb.controller.control = pbmit_blockquote;
		}
	});
}

function pbmit_mousehover_tooltip() {
	jQuery("<div id='pbmit-portfolio-cursor'><div class='pbmit-tooltip-content pbminfotech-box-content'></div></div>").appendTo("body");
	var pbmit_cursor = jQuery("#pbmit-portfolio-cursor");
	jQuery(document).on('mousemove', function(e) {
		var pbmit_x = e.clientX;
		var pbmit_y = e.clientY;
		pbmit_cursor.css({ "transform": "translate3d(" + pbmit_x + "px, " + pbmit_y + "px, 0px)" });
	})
	tooltiprecall();
}

function tooltiprecall() {	
	var pbmit_text = jQuery('.pbmit-element-portfolio-style-2 .pbminfotech-post-content');
	var pbmit_cursor = jQuery("#pbmit-portfolio-cursor"); 
	if (pbmit_text.length) {
		pbmit_text.each(function() {
			var element = jQuery(this);
			var pbmit_html = element.find('.pbminfotech-box-content').html();
			element.on('mouseenter', function() {
				pbmit_cursor.addClass('active').find('.pbmit-tooltip-content').html(pbmit_html);
			}).on('mouseleave', function(e) {
				pbmit_cursor.removeClass('active').find('.pbmit-tooltip-content').html();
			});
		});
	}
}

function pbmit_donation(){

	jQuery('#searchbar').focus();

	jQuery('#donate-buttons').on('click', '.amount-btn', function(e) {
		e.preventDefault();
		jQuery('.active').removeClass('active');
		jQuery(this).filter('.amount-btn').addClass("active");
		var value = jQuery(this).data('impact');
		jQuery(this).closest('div').find('p').text("" + value);
		jQuery('#other-input').find('input').val('');  
	});
}

// on ready
$(document).ready(function() {
    pbmit_title_animation();
	pbmit_extend_section();
	pbmit_testimonial_review();
	pbmit_thia_sticky();
	pbmit_donation();
});

// on resize
$(window).resize(function() {
	pbmit_title_animation();
	pbmit_img_animation();
});

// on load
$(window).on('load', function(){
	pbmit_mousehover_tooltip();
	pbmit_img_animation();
	pbmit_sticky();
	pbmit_sticky_special();
});

