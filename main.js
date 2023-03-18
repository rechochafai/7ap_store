$(window).scroll(function(){
    if($(window).scrollTop()){
        console.log("ok");
        $(".logo").addClass("active");
    }else{
        console.log("no");
        $(".logo").removeClass("active");
    }
});



$(".btn1").click(function(){
    $("#size").text($(this).parent().data("size"));
    $("#install").text($(this).parent().data("instaler"));
    $("#img").attr("src",$(this).parent().data("img"));
    $(".ioss").attr("data-ios",$(this).parent().data("lockerios"));
    $(".andoidd").attr("data-andoid",$(this).parent().data("lockerandoid"));

    $(".cpaBtn").attr("data-lockers",$(this).data("locker"));

    //$(this).data("locker");
    console.log($(this).data("locker"));

   setTimeout(function(){
    $(".pop-apps").css("display","flex");
   },1000);
});



function mobile(){
    if($(window).width() < 821){
        
    }else{
        console.log("pc");
        $(".container").html(`
            <div class="eror">
                <img src="img/eror.png" alt="">
                <p>Mobile Phone Not Detected</p>
                <p>Looks like you are trying to access this website from a non mobile phone device.</p>
            </div>

        `);
    }
};
mobile();



const search =() =>{
    const searchbox = document.getElementById("search-itms").value.toUpperCase();
    const product = document.querySelectorAll(".product-one");
    const gname = document.querySelectorAll(".nameGame");

    for (var i = 0; i < gname.length; i++){
        let match = product[i].getElementsByTagName("p")[0];

        if(match){
            let textvalue = match.textContent || match.innerHTML
            
            if(textvalue.toUpperCase().indexOf(searchbox) > -1){
                product[i].style.display = "";

            }else{
                product[i].style.display = "none";
            }
        }
    }
}




$(".cpaBtn").click(function(){
    $(".installLastBox").css("display","flex");
    var settimes = setInterval(lodFunc,50);
    var contor = 1;
    function lodFunc(){
        if(contor == 100){
            clearInterval(settimes);
            window.location.replace("https://txasgak.xyz" + "/" + `${$(".cpaBtn").data("lockers")}`);
        }else{
            contor = contor +1;
            $(".minbar").css("width",`${contor}%`);
            $("#porsenct").html(`${contor}%`);
        }
    }
});








