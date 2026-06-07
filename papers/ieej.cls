%%
%%% ieej.cls ((u)pLaTeX2e)
%%   for the Transactions of The Institute of Electrical Engineers of Japan
%%    by Motoaki Sato (ULS and Company), 2001-2022. 
%%     E-mail: teppei@uls.co.jp, http://www.uls.co.jp/
\ifx\directlua\@undefined
 \NeedsTeXFormat{pLaTeX2e}
\else
 \NeedsTeXFormat{LaTeX2e}
\fi
\ProvidesClass{ieej}
%%[2001/03/09 v1.0 for Transactions of IEEJ]
%%[2001/06/26 v1.0a for Transactions of IEEJ]
%% 電気学会部門誌への投稿手引の平成14年7月改正に基づく改訂
%%[2002/08/19 v2.0 for Transactions of IEEJ]
%%[2002/10/01 v2.0a for Transactions of IEEJ]
%%[2002/11/27 v2.0b for Transactions of IEEJ]
%%[2003/01/14 v2.1 for Transactions of IEEJ]
%%[2005/03/03 v2.2 for Transactions of IEEJ]
%%[2005/05/18 v2.3 for Transactions of IEEJ]
%%[2005/11/07 v2.4 for Transactions of IEEJ]
%%[2007/11/09 v2.5 for Transactions of IEEJ]
%%[2008/06/30 v2.6 for Transactions of IEEJ]
%%[2009/02/04 v2.7 for Transactions of IEEJ]
%% 電子ジャーナル化に伴う改訂
%%[2011/03/08 v3.0 for Transactions of IEEJ]
%%[2011/07/11 v3.1 for Transactions of IEEJ]
%%[2021/10/11 v4.0 for Transactions of IEEJ]
  [2022/04/06 v5.0 for Transactions of IEEJ]

%\newif\if@NTT
%\@ifundefined{kanjiskip}{\@NTTtrue
% \let\kanjiskip\jintercharskip
% \let\xkanjiskip\jasciikanjiskip
% \let\inhibitglue\relax
% }{\@NTTfalse\let\jmathkanjiskip\xkanjiskip}
%\@ifundefined{burasage}{}{\burasage`，=1\burasage`。=1}
%
%\newif\if@usejistfm \@usejistfmfalse
%\DeclareOption{usejistfm}{\@usejistfmtrue}

\def\ieej@warning{\ClassWarningNoLine{ieej}}
\def\ieejline@warning{\ClassWarning{ieej}}

%\newif\if@enable@uptex \@enable@uptexfalse
%\ifx\ucs\@undefined\else
% \ifnum\ucs"3000="3000
%  \@enable@uptextrue
% \fi
%\fi
\newif\if@enable@uptex \@enable@uptexfalse
\ifx\directlua\@undefined
 \def\kenc@ieej{JY2}
 \ifx\kenc@ieej\cy@encoding
  \@enable@uptextrue
 \fi
 %%
 \def\zw{zw}%
 \def\zh{zh}%
 \def\ieej@kanjiskip#1{\kanjiskip#1}
 \def\ieej@xkanjiskip#1{\xkanjiskip#1}% for kintou
\else
 \@enable@uptextrue
 \RequirePackage{luatexja}%
 %\RequirePackage{luatexja-fontspec}
 \def\ieej@kanjiskip#1{\ltjsetparameter{kanjiskip=#1}}
 \def\ieej@xkanjiskip#1{\ltjsetparameter{xkanjiskip=#1}}% for kintou
\fi

\newdimen\@JQ
\if@enable@uptex
 \@JQ=0.769362pt
\else
 \@JQ=0.7392507pt
\fi
\newdimen\@Q
 \@Q=0.71144pt

\newif\if@paper \@papertrue
\DeclareOption{paper}{\@papertrue}

\newif\if@letter \@letterfalse
\DeclareOption{letter}{\@lettertrue}
\newif\if@english \@englishfalse
\DeclareOption{english}{\@englishtrue}
\newif\if@comment \@commentfalse
\DeclareOption{comment}{\@commenttrue}
\newif\if@feature \@featurefalse
\DeclareOption{feature}{\@featuretrue\@commenttrue}
\newif\if@foreword \@forewordfalse
\DeclareOption{foreword}{\@forewordtrue\@paperfalse}

\newif\if@essay \@essayfalse
\DeclareOption{essay}{\@essaytrue}

%\newif\if@ExSum \@ExSumfalse
%\DeclareOption{ExtendedSummary}{\@ExSumtrue\@englishtrue\@paperfalse}

\newif\if@Proof \@Prooffalse
\DeclareOption{Proof}{\@Prooftrue}
\newif\if@cameraready \@camerareadyfalse
\DeclareOption{cameraready}{\@camerareadytrue}

\newif\if@ecaption \@ecaptionfalse
\DeclareOption{ecaption}{\@ecaptiontrue}

\newcounter{@paper}
%%\newif\if@landscape \@landscapefalse
\newcommand{\@ptsize}{}
\newif\if@restonecol
%%\newif\if@titlepage
%%\@titlepagefalse

%% for 2.1.4 and non pLaTeX2e compatibility
\@ifundefined{hour}{}{%
 \hour\time \divide\hour by 60\relax
 \@tempcnta\hour \multiply\@tempcnta 60\relax
 \minute\time \advance\minute-\@tempcnta
}
%%\newif\if@stysize \@stysizefalse
\newif\if@enablejfam \@enablejfamtrue
\newif\if@mathrmmc \@mathrmmcfalse
\DeclareOption{a4paper}{\setcounter{@paper}{1}%
  \setlength\paperheight {297mm}%
  \setlength\paperwidth  {210mm}}
\DeclareOption{10pt}{\renewcommand{\@ptsize}{0}}
\DeclareOption{11pt}{\renewcommand{\@ptsize}{1}}
\DeclareOption{12pt}{\renewcommand{\@ptsize}{2}}
\DeclareOption{tombow}{%
  \tombowtrue \tombowdatetrue
  \setlength{\@tombowwidth}{.1mm}%
  \@bannertoken{%
     \jobname\space:\space\number\year/\number\month/\number\day
      (\number\hour:\number\minute)}
  \maketombowbox}
\DeclareOption{tombo}{%
  \tombowtrue \tombowdatefalse
  \setlength{\@tombowwidth}{.1mm}%
  \maketombowbox}
\DeclareOption{mentuke}{%
  \tombowtrue \tombowdatefalse
  \setlength{\@tombowwidth}{\z@}%
  \maketombowbox}
\DeclareOption{tate}{\AtBeginDocument{\tate\message{《縦組モード》}}}
\DeclareOption{oneside}{\@twosidefalse}
\DeclareOption{twoside}{\@twosidetrue}
\DeclareOption{onecolumn}{\@twocolumnfalse}
\DeclareOption{twocolumn}{\@twocolumntrue}
%%\DeclareOption{titlepage}{\@titlepagetrue}
%%\DeclareOption{notitlepage}{\@titlepagefalse}
%%\DeclareOption{leqno}{\input{leqno.clo}}
%%\DeclareOption{fleqn}{\input{fleqn.clo}}
\DeclareOption{openbib}{%
  \AtEndOfPackage{%
   \renewcommand\@openbib@code{%
      \advance\leftmargin\bibindent
      \itemindent -\bibindent
      \listparindent \itemindent
      \parsep \z@
      }%
   \renewcommand\newblock{\par}}}
\DeclareOption{disablejfam}{\@enablejfamfalse}
\DeclareOption{draft}{\setlength\overfullrule{5pt}}
\DeclareOption{final}{\setlength\overfullrule{0pt}}
\ExecuteOptions{a4paper,10pt,twoside,twocolumn,fleqn,final}
\ProcessOptions\relax

\iftombow\else
 \AtBeginDvi{\special{pdf: pagesize width 210mm height 297mm}}%
\fi

%\def\kenc@JYn{\if@enable@uptex JY2\else JY1\fi}
%\def\kenc@JTn{\if@enable@uptex JT2\else JT1\fi}
\edef\kenc@JYn{\cy@encoding}
\edef\kenc@JTn{\ct@encoding}%\typeout{!!! \kenc@JTn}% 2012 OK

\def\Cjascale{0.924714}%

\ifx\directlua\@undefined
\if@enable@uptex
\if@cameraready
 \input{ieej-utf.fd}
\else
\DeclareFontShape{JY2}{mc}{m}{n}{%
  <5>     s*[0.995848]upjisr-h %  7Q
  <7>     s*[1.016171]upjisr-h % 10Q
  <8>     s*[0.978065]upjisr-h % 11Q
  <9>     s*[0.948427]upjisr-h % 12Q
  <10>    s*[0.924714]upjisr-h % 13Q
  <10.95> s*[0.974411]upjisr-h % 15Q
  <12>    s*[1.06698]upjisr-h  % 18Q
  <14.4>  s*[0.987944]upjisr-h % 20Q
  <17.28> s*[0.987944]upjisr-h % 24Q
  %<20.74> s*[0.960316]upjisr-h % 28Q
  %<24.88> s*[0.914881]upjisr-h % 32Q
  <-> s*[0.924714]upjisr-h
}{}
\DeclareFontShape{JY2}{gt}{m}{n}{%
  <5>     s*[0.995848]upjisg-h %  7Q
  <7>     s*[1.016171]upjisg-h % 10Q
  <8>     s*[0.978065]upjisg-h % 11Q
  <9>     s*[0.948427]upjisg-h % 12Q
  <10>    s*[0.924714]upjisg-h % 13Q
  <10.95> s*[0.974411]upjisg-h % 15Q
  <12>    s*[1.06698]upjisg-h  % 18Q
  <14.4>  s*[0.987944]upjisg-h % 20Q
  <17.28> s*[0.987944]upjisg-h % 24Q
  %<20.74> s*[0.960316]upjisg-h % 28Q
  %<24.88> s*[0.914881]upjisg-h % 32Q
  <->s*[0.924714]upjisg-h
}{}
%%
\DeclareFontShape{JT2}{mc}{m}{n}{%
  <5>     s*[0.995848]upjisr-v %  7Q
  <7>     s*[1.016171]upjisr-v % 10Q
  <8>     s*[0.978065]upjisr-v % 11Q
  <9>     s*[0.948427]upjisr-v % 12Q
  <10>    s*[0.924714]upjisr-v % 13Q
  <10.95> s*[0.974411]upjisr-v % 15Q
  <12>    s*[1.06698]upjisr-v  % 18Q
  <14.4>  s*[0.987944]upjisr-v % 20Q
  <17.28> s*[0.987944]upjisr-v % 24Q
  %<20.74> s*[0.960316]upjisr-v % 28Q
  %<24.88> s*[0.914881]upjisr-v % 32Q
  <-> s*[0.924714]upjisr-v
}{}
\DeclareFontShape{JT2}{gt}{m}{n}{%
  <5>     s*[0.995848]upjisg-v %  7Q
  <7>     s*[1.016171]upjisg-v % 10Q
  <8>     s*[0.978065]upjisg-v % 11Q
  <9>     s*[0.948427]upjisg-v % 12Q
  <10>    s*[0.924714]upjisg-v % 13Q
  <10.95> s*[0.974411]upjisg-v % 15Q
  <12>    s*[1.06698]upjisg-v  % 18Q
  <14.4>  s*[0.987944]upjisg-v % 20Q
  <17.28> s*[0.987944]upjisg-v % 24Q
  %<20.74> s*[0.960316]upjisg-v % 28Q
  %<24.88> s*[0.914881]upjisg-v % 32Q
  <->s*[0.924714]upjisg-v
}{}
\fi
\else
\if@cameraready
 \input{ieej-cameraready.fd}
\else
\DeclareFontShape{JY1}{mc}{m}{n}{%
  <5>     sfixed * [5.1748] jis %  7Q
  <6>     sfixed * [5.9141] jis %  8Q
  <7>     sfixed * [7.3926] jis % 10Q
  <8>     sfixed * [8.1318] jis % 11Q
  <9>     sfixed * [8.8711] jis % 12Q
  <10>    sfixed * [9.6104] jis % 13Q
  <10.95> sfixed * [11.089] jis % 15Q
  <12>    sfixed * [13.307] jis % 18Q
  <14.4>  sfixed * [14.785] jis % 20Q
  <17.28> sfixed * [17.742] jis % 24Q
  <20.74> sfixed * [20.699] jis % 28Q
  <24.88> sfixed * [23.656] jis % 32Q
  <->                       jis % 
}{}
%\DeclareFontShape{JY1}{mc}{bx}{n}{%
%  <5>     sfixed * [5.1748] jisg
%  <6>     sfixed * [5.9141] jisg
%  <7>     sfixed * [7.3926] jisg
%  <8>     sfixed * [8.1318] jisg
%  <9>     sfixed * [8.8711] jisg
%  <10>    sfixed * [9.6104] jisg
%  <10.95> sfixed * [11.089] jisg
%  <12>    sfixed * [13.307] jisg
%  <14.4>  sfixed * [14.785] jisg
%  <17.28> sfixed * [17.742] jisg
%  <20.74> sfixed * [20.699] jisg
%  <24.88> sfixed * [23.656] jisg
%  <->                       jisg
%}{}
\DeclareFontShape{JY1}{gt}{m}{n}{%
  <5>     sfixed * [5.1748] jisg
  <6>     sfixed * [5.9141] jisg
  <7>     sfixed * [7.3926] jisg
  <8>     sfixed * [8.1318] jisg
  <9>     sfixed * [8.8711] jisg
  <10>    sfixed * [9.6104] jisg
  <10.95> sfixed * [11.089] jisg
  <12>    sfixed * [13.307] jisg
  <14.4>  sfixed * [14.785] jisg
  <17.28> sfixed * [17.742] jisg
  <20.74> sfixed * [20.699] jisg
  <24.88> sfixed * [23.656] jisg
  <->                       jisg
}{}
%\DeclareFontShape{JY1}{gt}{bx}{n}{%
%  <5>     sfixed * [5.1748] jisg
%  <6>     sfixed * [5.9141] jisg
%  <7>     sfixed * [7.3926] jisg
%  <8>     sfixed * [8.1318] jisg
%  <9>     sfixed * [8.8711] jisg
%  <10>    sfixed * [9.6104] jisg
%  <10.95> sfixed * [11.089] jisg
%  <12>    sfixed * [13.307] jisg
%  <14.4>  sfixed * [14.785] jisg
%  <17.28> sfixed * [17.742] jisg
%  <20.74> sfixed * [20.699] jisg
%  <24.88> sfixed * [23.656] jisg
%  <->                       jisg
%}{}
\fi
\fi
\else
%\if@cameraready
% \input{ieej-lua.fd}
%\else
\DeclareFontShape{JY3}{mc}{m}{n}{%
  <5>     s*[0.995848]\ltj@stdmcfont:jfm=ujis %  7Q
  <7>     s*[1.016171]\ltj@stdmcfont:jfm=ujis % 10Q
  <8>     s*[0.978065]\ltj@stdmcfont:jfm=ujis % 11Q
  <9>     s*[0.948427]\ltj@stdmcfont:jfm=ujis % 12Q
  <10>    s*[0.924714]\ltj@stdmcfont:jfm=ujis % 13Q
  <10.95> s*[0.974411]\ltj@stdmcfont:jfm=ujis % 15Q
  <12>    s*[1.06698]\ltj@stdmcfont:jfm=ujis  % 18Q
  <14.4>  s*[0.987944]\ltj@stdmcfont:jfm=ujis % 20Q
  <17.28> s*[0.987944]\ltj@stdmcfont:jfm=ujis % 24Q
  %<20.74> s*[0.960316]\ltj@stdmcfont:jfm=ujis % 28Q
  %<24.88> s*[0.914881]\ltj@stdmcfont:jfm=ujis % 32Q
  <-> s*[0.924714]\ltj@stdmcfont:jfm=ujis
}{}
\DeclareFontShape{JY3}{gt}{m}{n}{%
  <5>     s*[0.995848]\ltj@stdgtfont:jfm=ujis %  7Q
  <7>     s*[1.016171]\ltj@stdgtfont:jfm=ujis % 10Q
  <8>     s*[0.978065]\ltj@stdgtfont:jfm=ujis % 11Q
  <9>     s*[0.948427]\ltj@stdgtfont:jfm=ujis % 12Q
  <10>    s*[0.924714]\ltj@stdgtfont:jfm=ujis % 13Q
  <10.95> s*[0.974411]\ltj@stdgtfont:jfm=ujis % 15Q
  <12>    s*[1.06698]\ltj@stdgtfont:jfm=ujis  % 18Q
  <14.4>  s*[0.987944]\ltj@stdgtfont:jfm=ujis % 20Q
  <17.28> s*[0.987944]\ltj@stdgtfont:jfm=ujis % 24Q
  %<20.74> s*[0.960316]\ltj@stdgtfont:jfm=ujis % 28Q
  %<24.88> s*[0.914881]\ltj@stdgtfont:jfm=ujis % 32Q
  <->s*[0.924714]\ltj@stdgtfont:jfm=ujis
}{}
%%%
\DeclareFontShape{JT3}{mc}{m}{n}{%
  <5>     s*[0.995848]\ltj@stdmcfont:jfm=ujisv %  7Q
  <7>     s*[1.016171]\ltj@stdmcfont:jfm=ujisv % 10Q
  <8>     s*[0.978065]\ltj@stdmcfont:jfm=ujisv % 11Q
  <9>     s*[0.948427]\ltj@stdmcfont:jfm=ujisv % 12Q
  <10>    s*[0.924714]\ltj@stdmcfont:jfm=ujisv % 13Q
  <10.95> s*[0.974411]\ltj@stdmcfont:jfm=ujisv % 15Q
  <12>    s*[1.06698]\ltj@stdmcfont:jfm=ujisv  % 18Q
  <14.4>  s*[0.987944]\ltj@stdmcfont:jfm=ujisv % 20Q
  <17.28> s*[0.987944]\ltj@stdmcfont:jfm=ujisv % 24Q
  %<20.74> s*[0.960316]\ltj@stdmcfont:jfm=ujisv % 28Q
  %<24.88> s*[0.914881]\ltj@stdmcfont:jfm=ujisv % 32Q
  <-> s*[0.924714]\ltj@stdmcfont:jfm=ujisv
}{}
\DeclareFontShape{JT3}{gt}{m}{n}{%
  <5>     s*[0.995848]\ltj@stdgtfont:jfm=ujisv %  7Q
  <7>     s*[1.016171]\ltj@stdgtfont:jfm=ujisv % 10Q
  <8>     s*[0.978065]\ltj@stdgtfont:jfm=ujisv % 11Q
  <9>     s*[0.948427]\ltj@stdgtfont:jfm=ujisv % 12Q
  <10>    s*[0.924714]\ltj@stdgtfont:jfm=ujisv % 13Q
  <10.95> s*[0.974411]\ltj@stdgtfont:jfm=ujisv % 15Q
  <12>    s*[1.06698]\ltj@stdgtfont:jfm=ujisv  % 18Q
  <14.4>  s*[0.987944]\ltj@stdgtfont:jfm=ujisv % 20Q
  <17.28> s*[0.987944]\ltj@stdgtfont:jfm=ujisv % 24Q
  %<20.74> s*[0.960316]\ltj@stdgtfont:jfm=ujisv % 28Q
  %<24.88> s*[0.914881]\ltj@stdgtfont:jfm=ujisv % 32Q
  <->s*[0.924714]\ltj@stdgtfont:jfm=ujisv
}{}
%\fi
\fi

\DeclareFontShape{\kenc@JYn}{mc}{bx}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{gt}{bx}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{b}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{b}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{m}{it}{<->ssub*mc/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{m}{sl}{<->ssub*mc/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{m}{sc}{<->ssub*mc/m/n}{}
\DeclareFontShape{\kenc@JYn}{gt}{m}{it}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{gt}{m}{sl}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{bx}{it}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{bx}{sl}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{b}{it}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JYn}{mc}{b}{sl}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{bx}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{gt}{bx}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{b}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{b}{n}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{m}{it}{<->ssub*mc/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{m}{sl}{<->ssub*mc/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{m}{sc}{<->ssub*mc/m/n}{}
\DeclareFontShape{\kenc@JTn}{gt}{m}{it}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{gt}{m}{sl}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{bx}{it}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{bx}{sl}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{b}{it}{<->ssub*gt/m/n}{}
\DeclareFontShape{\kenc@JTn}{mc}{b}{sl}{<->ssub*gt/m/n}{}
\ifx\directlua\@undefined\else
\renewcommand\jttdefault{\gtdefault}\@ltj@match@familytrue
\fi

\ifx\directlua\@undefined
\xspcode`+=3
\xspcode`\%=3
\xspcode`^^80=3
\xspcode`^^81=3
\xspcode`^^82=3
\xspcode`^^83=3
\xspcode`^^84=3
\xspcode`^^85=3
\xspcode`^^86=3
\xspcode`^^87=3
\xspcode`^^88=3
\xspcode`^^89=3
\xspcode`^^8a=3
\xspcode`^^8b=3
\xspcode`^^8c=3
\xspcode`^^8d=3
\xspcode`^^8e=3
\xspcode`^^8f=3
\xspcode`^^90=3
\xspcode`^^91=3
\xspcode`^^92=3
\xspcode`^^93=3
\xspcode`^^94=3
\xspcode`^^95=3
\xspcode`^^96=3
\xspcode`^^97=3
\xspcode`^^98=3
\xspcode`^^99=3
\xspcode`^^9a=3
\xspcode`^^9b=3
\xspcode`^^9c=3
\xspcode`^^9d=3
\xspcode`^^9e=3
\xspcode`^^9f=3
\xspcode`^^a0=3
\xspcode`^^a1=3
\xspcode`^^a2=3
\xspcode`^^a3=3
\xspcode`^^a4=3
\xspcode`^^a5=3
\xspcode`^^a6=3
\xspcode`^^a7=3
\xspcode`^^a8=3
\xspcode`^^a9=3
\xspcode`^^aa=3
\xspcode`^^ab=3
\xspcode`^^ac=3
\xspcode`^^ad=3
\xspcode`^^ae=3
\xspcode`^^af=3
\xspcode`^^b0=3
\xspcode`^^b1=3
\xspcode`^^b2=3
\xspcode`^^b3=3
\xspcode`^^b4=3
\xspcode`^^b5=3
\xspcode`^^b6=3
\xspcode`^^b7=3
\xspcode`^^b8=3
\xspcode`^^b9=3
\xspcode`^^ba=3
\xspcode`^^bb=3
\xspcode`^^bc=3
\xspcode`^^bd=3
\xspcode`^^be=3
\xspcode`^^bf=3
\xspcode`^^c0=3
\xspcode`^^c1=3
\xspcode`^^c2=3
\xspcode`^^c3=3
\xspcode`^^c4=3
\xspcode`^^c5=3
\xspcode`^^c6=3
\xspcode`^^c7=3
\xspcode`^^c8=3
\xspcode`^^c9=3
\xspcode`^^ca=3
\xspcode`^^cb=3
\xspcode`^^cc=3
\xspcode`^^cd=3
\xspcode`^^ce=3
\xspcode`^^cf=3
\xspcode`^^d0=3
\xspcode`^^d1=3
\xspcode`^^d2=3
\xspcode`^^d3=3
\xspcode`^^d4=3
\xspcode`^^d5=3
\xspcode`^^d6=3
\xspcode`^^d7=3
\xspcode`^^d8=3
\xspcode`^^d9=3
\xspcode`^^da=3
\xspcode`^^db=3
\xspcode`^^dc=3
\xspcode`^^dd=3
\xspcode`^^de=3
\xspcode`^^df=3
\xspcode`^^e0=3
\xspcode`^^e1=3
\xspcode`^^e2=3
\xspcode`^^e3=3
\xspcode`^^e4=3
\xspcode`^^e5=3
\xspcode`^^e6=3
\xspcode`^^e7=3
\xspcode`^^e8=3
\xspcode`^^e9=3
\xspcode`^^ea=3
\xspcode`^^eb=3
\xspcode`^^ec=3
\xspcode`^^ed=3
\xspcode`^^ee=3
\xspcode`^^ef=3
\xspcode`^^f0=3
\xspcode`^^f1=3
\xspcode`^^f2=3
\xspcode`^^f3=3
\xspcode`^^f4=3
\xspcode`^^f5=3
\xspcode`^^f6=3
\xspcode`^^f7=3
\xspcode`^^f8=3
\xspcode`^^f9=3
\xspcode`^^fa=3
\xspcode`^^fb=3
\xspcode`^^fc=3
\xspcode`^^fd=3
\xspcode`^^fe=3
\xspcode`^^ff=3
\fi

\ifx\directlua\@undefined
 \def\@setfontsize#1#2#3{\@nomath#1%
  \ifx\protect\@typeset@protect
    \let\@currsize#1%
  \fi
  \fontsize{#2}{#3}\selectfont
  \kanjiskip=0zw \@plus .1zw \@minus .025zw
  \xkanjiskip=0.25em \@plus 0.15em \@minus 0.06em
 }%
\else
 \def\@setfontsize#1#2#3{%
 %\@nomath#1%
  \ifx\protect\@typeset@protect
    \let\@currsize#1%
  \fi
  \fontsize{#2}{#3}\selectfont
  \ifdim\parindent>\z@
   \if@english
    \parindent=1em
   \else
    \parindent=1\zw
   \fi
  \fi
  \ltj@setpar@global
  \ltjsetkanjiskip\z@ plus .1\zw minus .01\zw
  \@tempskipa=\ltjgetparameter{xkanjiskip}
  \ifdim\@tempskipa>\z@
   %\if@slide
   % \ltjsetxkanjiskip .1em
   %\else
    \ltjsetxkanjiskip .25em plus .15em minus .06em
   %\fi
  \fi}
\fi

\if@english
 %% normalsize -->10pt 13Q 16.6H
 \renewcommand{\normalsize}{%
    \@setfontsize\normalsize\@xpt{16.6\@Q}%
  \abovedisplayskip 8\p@ \@plus1.5\p@ \@minus4\p@
  \abovedisplayshortskip \z@ \@plus2.5\p@
  \belowdisplayshortskip 5\p@ \@plus2.5\p@ \@minus2.5\p@
  \belowdisplayskip \abovedisplayskip
   \let\@listi\@listI}

 \normalsize
 \ifx\MakeRobust\@undefined \else
   \MakeRobust\normalsize
 \fi

 %\setbox0\hbox{\char\euc"A1A1}% "
 \setbox0\hbox{漢}
 \setlength\Cht{\ht0}
 \setlength\Cdp{\dp0}
 \setlength\Cwd{\wd0}
 \setlength\Cvs{\baselineskip}
 \setlength\Chs{\wd0}
 \setbox0=\box\voidb@x

 %% small-->9pt 12Q 14H
 \newcommand{\small}{%
  \@setfontsize\small\@ixpt{14\@Q}%
  \abovedisplayskip 8\p@ \@plus2.5\p@ \@minus3\p@
  \abovedisplayshortskip \z@ \@plus1.5\p@
  \belowdisplayshortskip 3\p@ \@plus1.5\p@ \@minus1.5\p@
  \def\@listi{\leftmargin\leftmargini
              \topsep 4\p@ \@plus2\p@ \@minus2\p@
              \parsep 2\p@ \@plus\p@ \@minus\p@
              \itemsep \parsep}%
  \belowdisplayskip \abovedisplayskip}

 %% footnotesize-->7pt 10Q 13H
 \newcommand{\footnotesize}{%
  \@setfontsize\footnotesize\@viipt{13\@Q}%
  \abovedisplayskip 5\p@ \@plus1.5\p@ \@minus3\p@
  \abovedisplayshortskip \z@ \@plus\p@
  \belowdisplayshortskip 2.5\p@ \@plus\p@ \@minus1.5\p@
  \def\@listi{\leftmargin\leftmargini
              \topsep 3\p@ \@plus\p@ \@minus\p@
              \parsep 2\p@ \@plus\p@ \@minus\p@
              \itemsep \parsep}%
  \belowdisplayskip \abovedisplayskip}

 %% Small-->8pt 11Q 13H
 \newcommand{\Small}{\@setfontsize\Small\@viiipt{13\@Q}}
\else
 %% normalsize -->10pt 13Q 20H
 \renewcommand{\normalsize}{%
    \@setfontsize\normalsize\@xpt{20\@Q}%
  \abovedisplayskip 10\p@ \@plus2\p@ \@minus5\p@
  \abovedisplayshortskip \z@ \@plus3\p@
  \belowdisplayshortskip 6\p@ \@plus3\p@ \@minus3\p@
   \belowdisplayskip \abovedisplayskip
   \let\@listi\@listI}

 %\normalsize
 \mcfamily\selectfont\normalsize
 \ifx\MakeRobust\@undefined \else
   \MakeRobust\normalsize
 \fi

 %\setbox0\hbox{\char\euc"A1A1}% "
 \setbox0\hbox{漢}
 \setlength\Cht{\ht0}
 \setlength\Cdp{\dp0}
 \setlength\Cwd{\wd0}
 \setlength\Cvs{\baselineskip}
 \setlength\Chs{\wd0}
 \setbox0=\box\voidb@x

 %% small-->9pt 12Q 16H
 \newcommand{\small}{%
  \@setfontsize\small\@ixpt{16\@Q}%
  \abovedisplayskip 8.5\p@ \@plus3\p@ \@minus4\p@
  \abovedisplayshortskip \z@ \@plus2\p@
  \belowdisplayshortskip 4\p@ \@plus2\p@ \@minus2\p@
  \def\@listi{\leftmargin\leftmargini
              \topsep 4\p@ \@plus2\p@ \@minus2\p@
              \parsep 2\p@ \@plus\p@ \@minus\p@
              \itemsep \parsep}%
  \belowdisplayskip \abovedisplayskip}

 %% footnotesize-->7pt 10Q 15H
 \newcommand{\footnotesize}{%
  \@setfontsize\footnotesize\@viipt{15\@Q}%
  \abovedisplayskip 6\p@ \@plus2\p@ \@minus4\p@
  \abovedisplayshortskip \z@ \@plus\p@
  \belowdisplayshortskip 3\p@ \@plus\p@ \@minus2\p@
  \def\@listi{\leftmargin\leftmargini
              \topsep 3\p@ \@plus\p@ \@minus\p@
              \parsep 2\p@ \@plus\p@ \@minus\p@
              \itemsep \parsep}%
  \belowdisplayskip \abovedisplayskip}

 %% Small-->8pt 11Q 15H
 \newcommand{\Small}{\@setfontsize\Small\@viiipt{15\@Q}}
\fi

\newcommand{\scriptsize}{\@setfontsize\scriptsize\@viipt\@viiipt}
\newcommand{\tiny}{\@setfontsize\tiny\@vpt\@vipt}
\newcommand{\large}{\@setfontsize\large\@xipt{23\@Q}}
\newcommand{\Large}{\@setfontsize\Large\@xiipt{23\@Q}}
\newcommand{\LARGE}{\@setfontsize\LARGE\@xivpt{27\@Q}}
\newcommand{\huge}{\@setfontsize\huge\@xviipt{31\@Q}}
\newcommand{\Huge}{\@setfontsize\Huge\@xxpt{30}}

%%\if@ExSum
%% \headheight \z@
%% \headsep    \z@
%% \topskip    1\Cht
%% \footskip   \z@
%% \textwidth  169mm
%%\else
 \headheight 6mm
 \headsep    3.5mm
 \topskip    1\Cht
 \footskip   9mm
 \textwidth  178.75mm %% 13x26x2+13x3=676+39=715H (178.75mm)
%%\fi
%\@settopoint\textwidth

\maxdepth   .5\topskip

\if@english
 %%\if@ExSum
 %% \baselineskip16\@Q
 %% \textheight 55\baselineskip
 %% \advance \textheight \topskip
 %% \advance \textheight .2mm %% limit .165mm
 %%\else
 \textheight 59\Cvs
 \advance \textheight \topskip
 %\advance \textheight .3mm %% limit .27mm
 %%\fi
\else
 \textheight 49\Cvs
 \advance \textheight \topskip
 \advance \textheight .15mm %% limit .12mm
\fi
%\@settopoint\textheight

\if@twocolumn
  \setlength\marginparsep{10\p@}
\else
  \setlength\marginparsep{10\p@}
\fi
\setlength\marginparpush{5\p@}

\topmargin\paperheight
\advance \topmargin -\textheight
\advance \topmargin -\headheight
\advance \topmargin -\headsep
\advance \topmargin -\footskip
\divide \topmargin \tw@
\advance \topmargin -1in
%\@settopoint\topmargin
\oddsidemargin\paperwidth
\advance \oddsidemargin -\textwidth
\divide \oddsidemargin \tw@
\advance \oddsidemargin -1in
%\@settopoint\oddsidemargin
\evensidemargin\oddsidemargin
%\@settopoint\evensidemargin

\marginparwidth 2in
%\@settopoint\marginparwidth

\if@english
 \footnotesep2.45mm
\else
 \footnotesep2.8mm
\fi
\skip\footins .75\Cvs \@plus 4\p@ \@minus 2\p@
\floatsep 1\Cvs \@plus 1.5mm \@minus 2mm
\textfloatsep 1.5\Cvs \@plus 2mm \@minus 2mm
\intextsep 1.5\Cvs \@plus 1.5mm \@minus 2mm
\dblfloatsep 1\Cvs \@plus 1.5mm \@minus 2mm
\dbltextfloatsep 1.5\Cvs \@plus 2mm \@minus 2mm

\@fptop 0\p@ \@plus 1fil
\@fpsep 8\p@ \@plus 2fil
\@fpbot 0\p@ \@plus 1fil
\@dblfptop 0\p@ \@plus 1fil
\@dblfpsep 8\p@ \@plus 2fil
\@dblfpbot 0\p@ \@plus 1fil
\partopsep \z@

\def\@listi{\leftmargin\leftmargini
  \parsep  4\p@ \@plus2\p@ \@minus\p@
  \topsep  8\p@ \@plus2\p@ \@minus4\p@
  \itemsep 4\p@ \@plus2\p@ \@minus\p@}
\let\@listI\@listi
\@listi
\def\@listii{\leftmargin\leftmarginii
   \labelwidth\leftmarginii \advance\labelwidth-\labelsep
   \topsep 4\p@ \@plus2\p@ \@minus\p@
   \parsep 2\p@ \@plus\p@  \@minus\p@
   \itemsep\parsep}
\def\@listiii{\leftmargin\leftmarginiii
   \labelwidth\leftmarginiii \advance\labelwidth-\labelsep
   \topsep    2\p@  \@plus\p@\@minus\p@
   \parsep    \z@
   \partopsep \p@ \@plus\z@ \@minus\p@
   \itemsep\topsep}
\def\@listiv {\leftmargin\leftmarginiv
              \labelwidth\leftmarginiv
              \advance\labelwidth-\labelsep}
\def\@listv  {\leftmargin\leftmarginv
              \labelwidth\leftmarginv
              \advance\labelwidth-\labelsep}
\def\@listvi {\leftmargin\leftmarginvi
              \labelwidth\leftmarginvi
              \advance\labelwidth-\labelsep}

\if@english
 \columnsep8mm
\else
 \columnsep9.75mm
\fi
\columnseprule 0\p@
\lineskip 1\p@
\normallineskip 1\p@
\renewcommand{\baselinestretch}{}
\parskip\z@
\parindent1\zw

\@lowpenalty   51
\@medpenalty  151
\@highpenalty 301
\setcounter{topnumber}{5}
\setcounter{bottomnumber}{5}
\setcounter{totalnumber}{10}
\setcounter{dbltopnumber}{5}
\renewcommand{\topfraction}{.95}
\renewcommand{\bottomfraction}{.95}
\renewcommand{\textfraction}{.05}
\renewcommand{\floatpagefraction}{.05}
\renewcommand{\dbltopfraction}{.95}
\renewcommand{\dblfloatpagefraction}{.05}

\if@Proof
 \def\@RH{\rlap{\smash{\raisebox{-1\headsep}%
  {\rule{0.01mm}{10mm}\rule{10mm}{0.01mm}}}}}
 \def\@LH{\llap{\smash{\raisebox{-1\headsep}%
  {\rule{10mm}{0.01mm}\rule{0.01mm}{10mm}}}}}
 \def\@RB{\rlap{\smash{\raisebox{1\footskip}%
  {\rule[-10mm]{0.01mm}{10mm}\rule{10mm}{0.01mm}}}}}
 \def\@LB{\llap{\smash{\raisebox{1\footskip}%
  {\rule{10mm}{0.01mm}\rule[-10mm]{0.01mm}{10mm}}}}}
 \def\pot@jobname{\smash{\raise7mm\llap{\LARGE\texttt{\jobname}}}}
\else
 \let\@RH\relax \let\@LH\relax \let\@RB\relax \let\@LB\relax 
 \let\pot@jobname\relax
\fi

\def\nombre@font{\small\sffamily}
\def\foot@font{\Small\sffamily\gtfamily}

\if@paper
\def\ps@ieej{\let\@mkboth\@gobbletwo
 \def\@oddfoot{\@LB
  \rlap{\Small\normalfont
   \textcopyright\ \f@YEAR\ 
   The Institute of Electrical Engineers of Japan.}\hfil
  {\nombre@font \thepage}\hfil
  \@RB}%
 \let\@evenfoot\@oddfoot
 \def\@evenhead{\@LH
  \hbox to \z@{\hbox to \textwidth{\leaders\hrule height.12mm\hfil}\hss}%
  \ieej@info\hfil\pot@jobname
  \@RH}%
 \def\@oddhead{\@LH
  \hbox to \z@{\hbox to \textwidth{\leaders\hrule height.12mm\hfil}\hss}%
  \ieej@info\hfil\pot@jobname
  \@RH}%
}
\else
\def\ps@ieej{\let\@mkboth\@gobbletwo
 \def\@oddfoot{\@LB
  \rlap{\Small\normalfont
   \textcopyright\ \f@YEAR\ 
   The Institute of Electrical Engineers of Japan.}\hfil
  {\nombre@font \thepage}\hfil
  \@RB}%
 \let\@evenfoot\@oddfoot
 \def\@evenhead{\@LH
  \hbox to \textwidth{\leaders\hrule height.12mm\hfil}\pot@jobname
  \@RH}%
 \def\@oddhead{\@LH
  \hbox to \textwidth{\leaders\hrule height.12mm\hfil}\pot@jobname
  \@RH}%
}
\fi

\def\ieej@info{%
 \smash{{%
  \renewcommand{\small}{\@setfontsize\small\@ixpt{16\@Q}}%
  \small
  \raise2mm\hbox{%
  \tabcolsep\z@
  \begin{tabular}[b]{l}
   \if@fieldDen
    IEEJ Journal of \csname Einfo@\@FIELD\endcsname\\[-.5mm]
    %Vol.\@VOL\ No.\@NO\ pp.\the\c@page--\pageref{ieej@lastpage}\hskip5.5mm
    Vol.\@VOL\ No.\@NO\ pp.\the\c@page--\pageref{LastPage}\hskip5.5mm
     DOI: 10.1541/ieej%
     \csname fieldDen@DOIinfo@\@FIELD\endcsname.\@VOL.\the\c@page
   \else
    電気学会論文誌\@FIELD（\csname Jinfo@\@FIELD\endcsname 部門誌）\\[-.5mm]
    IEEJ Transactions on \csname Einfo@\@FIELD\endcsname\\[-.5mm]
    %Vol.\@VOL\ No.\@NO\ pp.\the\c@page--\pageref{ieej@lastpage}\hskip5.5mm
    Vol.\@VOL\ No.\@NO\ pp.\the\c@page--\pageref{LastPage}\hskip5.5mm
     DOI: 10.1541/ieej\csname DOIinfo@\@FIELD\endcsname.\@VOL.\the\c@page
   \fi
  \end{tabular}%
  }}}%
}

\def\Jinfo@A{基礎・材料・共通}
\def\Jinfo@B{電力・エネルギー}
\def\Jinfo@C{電子・情報・システム}
\def\Jinfo@D{産業応用}
\def\Jinfo@E{センサ・マイクロマシン}
\def\Jinfo@X{XX}
\def\Einfo@A{Fundamentals and Materials}
\def\Einfo@B{Power and Energy}
\def\Einfo@C{Electronics, Information and Systems}
\def\Einfo@D{Industry Applications}
\def\Einfo@E{Sensors and Micromachines}
\def\Einfo@X{xx}
\def\DOIinfo@A{fms}
\def\DOIinfo@B{pes}
\def\DOIinfo@C{eiss}
\def\DOIinfo@D{ias}
\def\DOIinfo@E{smas}
\def\DOIinfo@X{xxs}
\def\fieldDen@DOIinfo@D{jia}

\def\ps@IEEJ{\let\@mkboth\@gobbletwo
 \def\@evenfoot{\@LB
  \hfil{\nombre@font \thepage}\hfil
  \llap{\foot@font 
   IEEJ \if@fieldDen Journal \else Trans.\ \fi
   \e@FIELD, Vol.\@VOL, No.\@NO, \f@YEAR\hskip3.25mm
  }%
  \@RB}%
 \let\@oddfoot\@evenfoot
 \def\@evenhead{\@LH
  \hbox to \z@{\hbox to \textwidth{\leaders\hrule height.12mm\hfil}\hss}%
  \hfil\smash{\raise 3mm\hbox{\small \head@title}}\hfil
  \@RH}%
 \def\@oddhead{\@LH
  \hbox to \z@{\hbox to \textwidth{\leaders\hrule height.12mm\hfil}\hss}%
  \hfil\smash{\raise 3mm\hbox{\small \head@title}}\hfil
  \@RH}%
}

%\if@ExSum
%\def\pp#1{\gdef\@pp{#1}}
%\def\@pp{}
%
%\def\ps@exsum{\let\@mkboth\@gobbletwo
% \def\@oddfoot{\@LB
%  \hfil{\nombre@font --\,\thepage\,--}\hfil
%  \@RB}%
% \let\@evenfoot\@oddfoot
% \def\@oddhead{\@LH
%  \hbox to \z@{\hbox to \textwidth{%
%   \leaders\hrule \@height-3.4mm \@depth 3.52mm\hfil}\hss}%
%  \smash{\raise -1.4mm\hbox{\Large Extended Summary}}\hfil
%  \ifx\@pp\empty\else
%   \smash{\raise -1.4mm\hbox{\small 本文は pp.\@pp}}%
%  \fi
%  \@RH}%
% \let\@evenhead\@oddhead
%}
%\fi

\def\jtitle{\@ifnextchar[% ]
 {\d@jtitle}{\s@jtitle}}

\def\m@headlength#1{%
 \setbox\@tempboxa\hbox{\def\\{\unskip\ignorespaces}%
  \small #1}%
  \ifdim \wd\@tempboxa > 174mm
   \ieej@warning{Title for header is too wide, make it shorter}\fi
}

\def\ieejhead@etal{%
 \if@english
  \ \textit{et al.}%
 \else
  ，他%
 \fi
}

\def\output@head@author{%
 （{\let\Gspace\relax
   \if@english\else
    \if@kanjiheadname
     \spaceskip-0.0001\zw
    \fi
   \fi
   \@header@author
   \ifnum\@totalnumber=\@ne\else
    \ieejhead@etal
   \fi}）%
}
\if@foreword
 \let\output@head@author\relax
\fi

\def\d@jtitle[#1]#2{%
 %\if@comment\if@feature
 % \gdef\head@title{特集解説}\else
 %  \gdef\head@title{解\hskip1\zw 説}\fi
 %\else
  \gdef\head@title{\def\\{\unskip\ignorespaces}%
   #1\output@head@author}%
  \m@headlength{#1\output@head@author}%
 %\fi
 \gdef\@jtitle{#2}}

\def\s@jtitle#1{%
 %\if@comment\if@feature
 % \gdef\head@title{特集解説}\else
 %  \gdef\head@title{解\hskip1\zw 説}\fi
 %\else
  \gdef\head@title{\def\\{\unskip\ignorespaces}%
   #1\output@head@author}%
  \m@headlength{#1\output@head@author}%
 %\fi
 \gdef\@jtitle{#1}}

\def\@jtitle{}
\def\head@title{}

\if@foreword
 \def\etitle#1{\gdef\foot@etitle{\footnotetext[0]{#1}}}
 \def\foot@etitle{}
\else
 \def\etitle#1{\gdef\@etitle{#1}}
 \def\@etitle{}
\fi

\def\jsubtitle#1{\gdef\@jsubtitle{#1}}
\def\@jsubtitle{}

\def\esubtitle#1{\gdef\@esubtitle{#1}}
\def\@esubtitle{}

\if@english
 \let\title\jtitle
 \let\subtitle\jsubtitle
\fi

\newtoks\@authorlist
\newcount\@authorcnt
\newcount\@alcnt
\newcount\p@alcnt
 \p@alcnt=12\relax
\newcount\@totalnumber
\newbox\@tempboxb
\newbox\@tempboxc
\newbox\@tempboxd

\def\authorlist#1{%
 \if@english\let\authorentry\Eauthorentry\fi
  \@authorlist={#1}\the\@authorlist
}

\def\name@expandafter#1#2{%
 \def\next{#1}%
 \protected@edef\@tempa{#2}%
 \ifx\@tempa\@empty
  \ieejline@warning{author's name is empty!}%
  \def\@tempa{\@empty}%
 \fi
 \expandafter\next\@tempa}
\def\chk@name#1{%
 \name@expandafter\@chk@name{#1}\@nil}
\def\@chk@name#1#2\@nil{\def\get@oneword{#1}}

\def\fmt@Jan#1{%
 \@temptokena{#1}%
 \def\hold@name{\the\@temptokena\unskip}%
 \chk@name{\the\@temptokena}%
 \setbox\@tempboxc\hbox{\get@oneword}%
 \ifdim \wd\@tempboxc=1\zw
  \setbox\@tempboxd\hbox{\spaceskip100mm \hold@name}%
  \ifdim \wd\@tempboxd < 100mm
   \if@foreword\else
    \ieej@warning{Author's name "#1" doesn't have a space}%
   \fi
   \let\@authorname\hold@name
  \else
   \setbox\@tempboxc\hbox{\hold@name}%
   \ifdim \wd\@tempboxc > 4\zw
    \def\@authorname{\spaceskip1\zw \hold@name}%
   \else
    \def\@checkbox##1 ##2\@nil{%
     \global\setbox\@tempboxa\hbox{##1}\global\setbox\@tempboxb\hbox{##2}}%
    \edef\@tempcheck{\expandafter\@checkbox #1\@nil}\@tempcheck
    \def\@tempy##1 ##2\@nil{\hbox{%
     \ifdim \wd\@tempboxa < 2\zw
      \hbox to 2\zw{##1\hss}%
     \else
      \hbox{##1}%
     \fi
     \hskip1\zw
     \ifdim \wd\@tempboxb < 2\zw
      \hbox to 2\zw{\hss ##2}%
     \else
      \hbox{##2}%
     \fi
    }}%
    \edef\@authorname{\expandafter\@tempy\the\@temptokena\@nil}%
   \fi
  \fi
 \else
  \ifdim\wd\@tempboxc=\z@ %% for 外字 (\G)
   \def\Gspace{\hspace{1\zw}}%
   \def\@authorname{\spaceskip1\zw \hold@name}%
  \else
   \let\@authorname\hold@name
  \fi
 \fi
}

\def\get@al#1{%
 \def\@noaffi{none}\def\@tempaffi{#1}%
 \ifx\@noaffi\@tempaffi\else
  \@for\get@label:=#1\do{%
   \@ifundefined{al@\get@label}%
    {%
     \global\advance \@alcnt \@ne
     \expandafter\xdef\csname al@\get@label\endcsname{\the\@alcnt}%
     \global\advance \@tempcnta \@ne
     \protected@xdef\plural@affi{\plural@affi
      \ifnum\@tempcnta=\@ne
       \adj@affimark{$^{\@fnsymbol{\csname al@\get@label\endcsname}}$}%
      \else
       \adj@affimark{$^{,\@fnsymbol{\csname al@\get@label\endcsname}}$}%
      \fi
     }%
    }%
    {%
     \global\advance \@tempcnta \@ne
     \protected@xdef\plural@affi{\plural@affi
      \ifnum\@tempcnta=\@ne
       \adj@affimark{$^{\@fnsymbol{\csname al@\get@label\endcsname}}$}%
      \else
       \adj@affimark{$^{,\@fnsymbol{\csname al@\get@label\endcsname}}$}%
      \fi
     }%
    }%
  }%
 \fi
}

\def\plural@affi{}
\def\adj@affimark#1{\if@english\raise1.1mm\hbox{#1}\else #1\fi}

\def\authorentry{\@ifnextchar[%% ]
 {\E@ae}{\NE@ae}}
\def\NE@ae#1#2#3#4{\@ifnextchar[%% ]
  {\NE@aeP{#1}{#2}{#3}{#4}}%       no Email with present affi.
  {\NE@aeNP{#1}{#2}{#3}{#4}}}%     no Email without present affi.
\def\E@ae[#1]#2#3#4#5{\@ifnextchar[%% ]
  {\E@aeP[#1]{#2}{#3}{#4}{#5}}%    Email with present affi.
  {\E@aeNP[#1]{#2}{#3}{#4}{#5}}}%  Email without present affi.

\def\ft@mailaddress#1{%
 \protected@xdef\@mailaddress{%
  \@mailaddress
  \protect\footnotetext[0]{#1}}%
}
\def\@mailaddress{}

\def\ss@mailaddress{%
 \protect\@textsuperscript{%(
  \normalfont\theenumii)}%
}

\def\header@author#1{\gdef\@header@author{#1}}
\def\@header@author{}

\newif\if@kanjiheadname \@kanjiheadnamefalse
\def\chk@headname#1{%
 \chk@name{#1}%
 \expandafter\ifcat\get@oneword 亜\global\@kanjiheadnametrue\fi
}

\def\NE@aeNP#1#2#3#4{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#4}%
 \def\al@none{0}%
 %% author's name in Japanese
 \fmt@Jan{#1}%
 \expandafter\protected@xdef\csname @Jauthorname\number\@authorcnt\endcsname{%
  \@authorname\kern\z@\plural@affi}%
 %% author's name in English
 \@temptokena{#2}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #3@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#1}%
  \chk@headname{#1}%
 \fi
}

\def\NE@aeP#1#2#3#4[#5]{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#4}%
 \def\al@none{0}%
 \@ifundefined{p@al@#5}%
  {\global\advance \p@alcnt \@ne
   \expandafter\xdef\csname p@al@#5\endcsname{\the\p@alcnt}}%
  {\relax}%
 %% author's name in Japanese
 \fmt@Jan{#1}%
 \expandafter\protected@xdef\csname @Jauthorname\number\@authorcnt\endcsname{%
  \@authorname\kern\z@\plural@affi
  $^{\@fnsymbol{\csname p@al@#5\endcsname}}$}%
 %% author's name in English
 \@temptokena{#2}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi
  $^{\@fnsymbol{\csname p@al@#5\endcsname}}$}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #3@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#1}%
  \chk@headname{#1}%
 \fi
}

\def\E@aeNP[#1]#2#3#4#5{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#5}%
 \def\al@none{0}%
 %% author's name in Japanese
 \def\@tempa{#1}%
 \ifx\@tempa\empty
  \let\ss@mailaddress\relax
 \else
  \stepcounter{enumii}%
  \ft@mailaddress{\hbox to \z@{\hss % (
   \theenumii)\hskip.25\zw}Correspondence to: #1}%
 \fi
 \fmt@Jan{#2}%
 \expandafter\protected@xdef\csname @Jauthorname\number\@authorcnt\endcsname{%
  \@authorname\kern\z@\plural@affi\ss@mailaddress}%
 %% author's name in English
 \@temptokena{#3}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi\ss@mailaddress}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #4@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#2}%
  \chk@headname{#2}%
 \fi
}

\def\E@aeP[#1]#2#3#4#5[#6]{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#5}%
 \def\al@none{0}%
 \@ifundefined{p@al@#6}%
  {\global\advance \p@alcnt \@ne
   \expandafter\xdef\csname p@al@#6\endcsname{\the\p@alcnt}}%
  {\relax}%
 %% author's name in Japanese
 \def\@tempa{#1}%
 \ifx\@tempa\empty
  \let\ss@mailaddress\relax
 \else
  \stepcounter{enumii}%
  \ft@mailaddress{\hbox to \z@{\hss % (
   \theenumii)\hskip.25\zw}Correspondence to: #1}%
 \fi
 \fmt@Jan{#2}%
 \expandafter\protected@xdef\csname @Jauthorname\number\@authorcnt\endcsname{%
  \@authorname\kern\z@\plural@affi
  $^{\@fnsymbol{\csname p@al@#6\endcsname}}$\ss@mailaddress}%
 %% author's name in English
 \@temptokena{#3}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi
  $^{\@fnsymbol{\csname p@al@#6\endcsname}}$\ss@mailaddress}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #4@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#2}%
  \chk@headname{#2}%
 \fi
}

\def\Eauthorentry{\@ifnextchar[%% ]
 {\E@Eae}{\NE@Eae}}
\def\NE@Eae#1#2#3{\@ifnextchar[%% ]
  {\NE@EaeP{#1}{#2}{#3}}%   no Email with present aff.
  {\NE@EaeNP{#1}{#2}{#3}}}% no Email without present aff.
\def\E@Eae[#1]#2#3#4{\@ifnextchar[%% ]
  {\E@EaeP[#1]{#2}{#3}{#4}}%    Email with present aff.
  {\E@EaeNP[#1]{#2}{#3}{#4}}}%  Email without present aff.

\def\NE@EaeNP#1#2#3{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#3}%
 \def\al@none{0}%
 %% author's name in English
 \@temptokena{#1}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #2@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#1}%
 \fi
}

\def\NE@EaeP#1#2#3[#4]{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#3}%
 \def\al@none{0}%
 \@ifundefined{p@al@#4}%
  {\global\advance \p@alcnt \@ne
   \expandafter\xdef\csname p@al@#4\endcsname{\the\p@alcnt}}%
  {\relax}%
 %% author's name in English
 \@temptokena{#1}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi
  \adj@affimark{$^{\@fnsymbol{\csname p@al@#4\endcsname}}$}}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #2@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#1}%
 \fi
}

\def\E@EaeNP[#1]#2#3#4{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#4}%
 \def\al@none{0}%
 %% author's name in English
 \def\@tempa{#1}%
 \ifx\@tempa\empty
  \let\ss@mailaddress\relax
 \else
  \stepcounter{enumii}%
  \ft@mailaddress{\hbox to \z@{\hss % (
   \theenumii)\hskip.25\zw}Correspondence to: #1}%
 \fi
 \@temptokena{#2}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi
  \nobreak\adj@affimark{\ss@mailaddress}}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #3@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#2}%
 \fi
}

\def\E@EaeP[#1]#2#3#4[#5]{%
 \@tempcnta\z@
 \advance \@authorcnt \@ne
 %% author label
 \get@al{#4}%
 \def\al@none{0}%
 \@ifundefined{p@al@#5}%
  {\global\advance \p@alcnt \@ne
   \expandafter\xdef\csname p@al@#5\endcsname{\the\p@alcnt}}%
  {\relax}%
 %% author's name in English
 \def\@tempa{#1}%
 \ifx\@tempa\empty
  \let\ss@mailaddress\relax
 \else
  \stepcounter{enumii}%
  \ft@mailaddress{\hbox to \z@{\hss % (
   \theenumii)\hskip.25\zw}Correspondence to: #1}%
 \fi
 \@temptokena{#2}%
 \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
  \the\@temptokena\nobreak\plural@affi
  \adj@affimark{$^{\@fnsymbol{\csname p@al@#5\endcsname}}$}%
  \nobreak\adj@affimark{\ss@mailaddress}}%
 %% membership
 \expandafter\xdef\csname @authmbrship\number\@authorcnt\endcsname{%
  \csname #3@member\endcsname}%
 \global\@totalnumber\@authorcnt
 \def\plural@affi{}%
 %% authorname in header
 \ifnum\@authorcnt=\@ne
  \header@author{#2}%
 \fi
}

%% [paper], [letter]
\def\Jbreakauthorline#1{%
 \@for\@breakauthor:=#1\do{%
  \expandafter\gdef\csname J@breakauthorline\@breakauthor\endcsname{\cr}%
 }%
 \@authorcnt\z@
 \loop\ifnum \@authorcnt < \@totalnumber
  \advance \@authorcnt \@ne
  \@ifundefined{J@breakauthorline\number\@authorcnt}%
   {\expandafter\gdef\csname J@breakauthorline\number\@authorcnt\endcsname{&}}%
   {\relax}%
 \repeat
 %%
 \@for\@chktotalnumber:=#1\do{%
  \ifnum\@totalnumber=\@chktotalnumber
  \expandafter\gdef\csname J@breakauthorline\@chktotalnumber\endcsname{}%
  \fi
 }%
}

\def\Jauthoralign#1{\gdef\@Jauthoralign{#1}}
\Jauthoralign{2}
\newcount\@limitnum \@limitnum5\relax

\def\@outputJauthorlist{%
 \Jbreakauthorline{3,6,9,12,15,18,21,24,27,30}%
 \def\m@member{正\hskip1\zw \@plus 1\zw 員}%
 \def\a@member{准\hskip1\zw \@plus 1\zw 員}%
 \def\n@member{非会員}%
 \def\l@member{終身会員}%
 \def\s@member{学生員}%
 \def\h@member{名誉員}%
 \def\S@member{上級会員}%
 \def\f@member{フェロー}%
 \@authorcnt\z@
 \ifnum\@Jauthoralign=\tw@
  \loop\ifnum \@authorcnt < \@totalnumber
   \advance \@authorcnt \@ne
   \protected@xdef\align@author{\align@author
    \csname @authmbrship\number\@authorcnt\endcsname
     & \csname @Jauthorname\number\@authorcnt\endcsname
      \ifodd\@authorcnt
       \ifnum\@authorcnt=\@totalnumber\cr\else &\fi
      \else
       \cr
      \fi
   }%
  \repeat
 \else
  \ifnum \@totalnumber>4\relax
   \@limitnum\@totalnumber
   \divide \@limitnum \thr@@
   \global\multiply \@limitnum \thr@@
   %\typeout{!!\the\@limitnum/\the\@totalnumber}%
   \@tempcnta\@totalnumber
   \advance \@tempcnta -\@limitnum
   \ifnum\@tempcnta=\tw@
    \loop\ifnum \@authorcnt < \@limitnum
     \advance \@authorcnt \@ne
     \protected@xdef\align@author{\align@author
      \csname @authmbrship\number\@authorcnt\endcsname
       & \csname @Jauthorname\number\@authorcnt\endcsname
	 \csname J@breakauthorline\number\@authorcnt\endcsname
     }%
    \repeat
   \else
    \loop\ifnum \@authorcnt < \@totalnumber
     \advance \@authorcnt \@ne
     \protected@xdef\align@author{\align@author
      \ifnum\@tempcnta=\z@\else
       \ifnum\@authorcnt=\@totalnumber
        & & 
       \fi
      \fi
       \csname @authmbrship\number\@authorcnt\endcsname
        & \csname @Jauthorname\number\@authorcnt\endcsname
	  \csname J@breakauthorline\number\@authorcnt\endcsname
     }%
    \repeat
    \global\@limitnum\@totalnumber
   \fi
  \else
   \loop\ifnum \@authorcnt < \@totalnumber
    \advance \@authorcnt \@ne
    \protected@xdef\align@author{\align@author
     \csname @authmbrship\number\@authorcnt\endcsname
      & \csname @Jauthorname\number\@authorcnt\endcsname
        \csname J@breakauthorline\number\@authorcnt\endcsname
    }%
   \repeat
  \fi
 \fi
 \align@author
}
\def\align@author{}

\def\@outputtherest{% 5,8,11,14,17,...
 \@authorcnt\@limitnum
 \def\m@member{正\hskip1\zw \@plus 1\zw 員}%
 \def\a@member{准\hskip1\zw \@plus 1\zw 員}%
 \def\n@member{非会員}%
 \def\l@member{終身会員}%
 \def\s@member{学生員}%
 \def\h@member{名誉員}%
 \def\S@member{上級会員}%
 \def\f@member{フェロー}%
 %\typeout{!!!\the\@limitnum / \the\@totalnumber}%
 \loop\ifnum \@authorcnt < \@totalnumber
  \advance \@authorcnt \@ne
  \protected@xdef\rest@author{\protect\authorname@font
   \rest@author
   \hskip1\zw
   {\mbrship@font \csname @authmbrship\number\@authorcnt\endcsname}%
   \hskip1\zw\lower.1\zh\hbox{%
    \csname @Jauthorname\number\@authorcnt\endcsname
   }%
   \ifnum\@authorcnt=\@totalnumber
    \hskip1\zw
   \fi
  }%
 \repeat
 \rest@author
}
\def\rest@author{}

\def\breakauthorline#1{%
 \@for\@breakauthor:=#1\do{%
  \expandafter\gdef\csname @breakauthorline\@breakauthor\endcsname{\\}%
 }%
 \@authorcnt\z@
 \loop\ifnum \@authorcnt < \@totalnumber
  \advance \@authorcnt \@ne
   \@ifundefined{@breakauthorline\number\@authorcnt}%
    {\expandafter\gdef\csname @breakauthorline\number\@authorcnt\endcsname
     {\relax}}%
    {\relax}%
 \repeat
}

%% [paper], [letter]
\def\@outputEauthorlist{%
 \def\m@member{Member}%
 \def\n@member{Non-member}%
 \def\a@member{Associate Member}%
 \def\l@member{Life Member}%
 \def\s@member{Student Member}%
 \def\h@member{Honorary Member}%
 \def\S@member{Senior Member}%
 \def\f@member{Fellow}%
 \@authorcnt\z@
 \loop\ifnum \@authorcnt < \@totalnumber
  \advance \@authorcnt \@ne 
   \mbox{%
    \csname @Eauthorname\number\@authorcnt\endcsname, 
    \csname @authmbrship\number\@authorcnt\endcsname
    \ifnum \@authorcnt < \@totalnumber\nobreak,\fi
   }
   \csname @breakauthorline\number\@authorcnt\endcsname
 \repeat
}

%% [english], [letter,english]
\def\Eauthoralign#1{\gdef\@Eauthoralign{#1}}
\Eauthoralign{2}
\newcount\e@limitnum %\e@limitnum3\relax

\def\@outputauthorlist{%
 \def\m@member{Member}%
 \def\n@member{Non-member}%
 \def\a@member{Associate Member}%
 \def\l@member{Life Member}%
 \def\s@member{Student Member}%
 \def\h@member{Honorary Member}%
 \def\S@member{Senior Member}%
 \def\f@member{Fellow}%
 \@authorcnt\z@
 \ifnum\@Eauthoralign=\@ne
  \loop\ifnum \@authorcnt < \@totalnumber
   \advance \@authorcnt \@ne
   \protected@xdef\align@author{\align@author
    {\authorname@font
     \csname @Eauthorname\number\@authorcnt\endcsname\hskip.75em}%
      & \csname @authmbrship\number\@authorcnt\endcsname
     \ifnum\@Eauthoralign=\@ne
      \cr
     \else
      \ifodd\@authorcnt
       \ifnum\@authorcnt=\@totalnumber\cr \else \unskip, & \fi
      \else
       \cr
      \fi
     \fi
   }%
  \repeat
 \else
  \global\e@limitnum\@totalnumber
  \ifnum \@totalnumber>\tw@
   \divide \e@limitnum \tw@
   \global\multiply \e@limitnum \tw@
   %\typeout{!!\the\e@limitnum/\the\@totalnumber}%
  \fi
  %%
  \loop\ifnum \@authorcnt < \e@limitnum %\@totalnumber
   \advance \@authorcnt \@ne
   \protected@xdef\align@author{\align@author
    {\authorname@font
     \csname @Eauthorname\number\@authorcnt\endcsname\hskip.75em}%
      & \csname @authmbrship\number\@authorcnt\endcsname
     \ifnum\@Eauthoralign=\@ne
      \cr
     \else
      \ifodd\@authorcnt
       \ifnum\@authorcnt=\e@limitnum\cr \else \unskip, & \fi
      \else
       \cr
      \fi
     \fi
   }%
  \repeat
 \fi
 \align@author
}

\def\@outputEtherest{%
 \def\m@member{Member}%
 \def\n@member{Non-member}%
 \def\a@member{Associate Member}%
 \def\l@member{Life Member}%
 \def\s@member{Student Member}%
 \def\h@member{Honorary Member}%
 \def\S@member{Senior Member}%
 \def\f@member{Fellow}%
 %\typeout{!!\the\e@limitnum/\the\@totalnumber}%
 \ifnum\@totalnumber=\e@limitnum
 \else
  \@authorcnt\@totalnumber
  \protected@xdef\Erest@author{{\authorname@font
   \csname @Eauthorname\number\@authorcnt\endcsname\hskip.75em}%
    \csname @authmbrship\number\@authorcnt\endcsname}%
 \fi
 \Erest@author
}
\def\Erest@author{}

\newcount\chk@alcnt
\newcount\chk@p@alcnt
\if@english
\def\affiliate[#1]#2{%
 \advance \chk@alcnt \@ne
 \@ifundefined{al@#1}%
  {\expandafter\def\csname al@#1\endcsname{1}%
   \ieej@warning{check the label "#1", it does not correspond to
     ^^J\space\space any labels in \string\authorentry\space command}%
  }{}%
 \bgroup
  \def\\{\hfil\protect\break}%
  \protected@xdef\@affiliate{\@affiliate
   \protect\footnotetext[\csname al@#1\endcsname]{#2}}%
 \egroup
}
\def\@affiliate{}

\def\paffiliate[#1]#2{%
 \advance \chk@p@alcnt \@ne
 \@ifundefined{p@al@#1}%
  {\expandafter\def\csname p@al@#1\endcsname{1}%
   \ieej@warning{check the label "#1", it does not correspond to
    ^^J\space\space any labels in \string\authorentry\space command}%
  }{}%
 \bgroup
  \def\\{\hfil\protect\break}%
  \protected@xdef\p@affiliate{\p@affiliate
   \protect\footnotetext[\csname p@al@#1\endcsname]{#2}}%
 \egroup
}
\def\p@affiliate{}

\else

\def\affiliate[#1]#2#3{%
 \advance \chk@alcnt \@ne
 \@ifundefined{al@#1}%
  {\expandafter\def\csname al@#1\endcsname{1}%
   \ieej@warning{check the label "#1", it does not correspond to
     ^^J\space\space any labels in \string\authorentry\space command}%
  }{}%
 \bgroup
  \def\\{\hfil\protect\break}%
  \protected@xdef\@affiliate{\@affiliate
   \protect\footnotetext[\csname al@#1\endcsname]{#2\\ #3}}%
 \egroup
}
\def\@affiliate{}

\def\paffiliate[#1]#2#3{%
 \advance \chk@p@alcnt \@ne
 \@ifundefined{p@al@#1}%
  {\expandafter\def\csname p@al@#1\endcsname{1}%
   \ieej@warning{check the label "#1", it does not correspond to
    ^^J\space\space any labels in \string\authorentry\space command}%
  }{}%
 \bgroup
  \def\\{\hfil\protect\break}%
  \protected@xdef\p@affiliate{\p@affiliate
   \protect\footnotetext[\csname p@al@#1\endcsname]{#2\\ #3}}%
 \egroup
}
\def\p@affiliate{}
\fi

\def\NoteOnArticle#1{%
 \protected@xdef\@NoteOnArticle{%
  \@NoteOnArticle
  \protect\footnotetext[0]{#1}}% \protect\vspace{\baselineskip}
}
\def\@NoteOnArticle{}

\def\NoteIntConf#1{%
 \protected@xdef\@NoteIntConf{%
  \@NoteIntConf
  \protect\footnotetext[0]{#1}}% \protect\vspace{\baselineskip}
}
\def\@NoteIntConf{}

\newbox\@abstractbox
\newbox\j@keywordbox
\newbox\e@keywordbox
\def\abstract{\global\setbox\@abstractbox=\hbox\bgroup
 \begin{minipage}[t]{165.75mm}%
  \normalsize\normalfont\parindent 3.25mm\ignorespaces}
\def\endabstract{\end{minipage}\egroup}

\def\jkeyword{\global\setbox\j@keywordbox=\hbox\bgroup
 \begin{minipage}[t]{165.75mm}%
  \small{\bfseries キーワード\hbox to 1\zw{\hss ：\hss}}\ignorespaces}
\def\endjkeyword{\end{minipage}\egroup}

\def\ekeyword{\global\setbox\e@keywordbox=\hbox\bgroup
 \begin{minipage}[t]{165.75mm}%
  \small{\bfseries Keywords:\ }\ignorespaces}
\def\endekeyword{\end{minipage}\egroup}

\if@english 
 \let\keyword\ekeyword
 \let\endkeyword\endekeyword
\fi

\if@english
 \def\@acceptance{\par
  \ifx \@received\empty\else
   \bgroup
    \ifx\@revised\@empty
     \noindent\hfil
     (\@received)\par
    \else
     \noindent\hfil
     (\@received, \@revised)\par
    \fi
   \egroup
  \fi
 }
 \def\received#1#2#3{\def\@temp@m{#2}\ifx \@temp@m\empty\def\@temp@m{0}\fi
  \def\@recmonth{%
   \ifcase\@temp@m xxx\or Jan.\or Feb.\or March\or April\or 
    May\or June\or July\or Aug.\or Sep.\or Oct.\or 
    Nov.\or Dec.\fi}%
  \gdef\@received{Manuscript\ received\ \@recmonth\ 
   \ignorespaces #3\unskip,\ \ignorespaces #1\unskip}%
 }
 \def\revised#1#2#3{%
  \def\@revmonth{\def\@temp@m{#2}\ifx \@temp@m\empty\def\@temp@m{0}\fi
   \ifcase\@temp@m xxx\or Jan.\or Feb.\or March\or April\or 
    May\or June\or July\or Aug.\or Sep.\or Oct.\or 
    Nov.\or Dec.\fi}%
  \gdef\@revised{revised\ \@revmonth\ 
   \ignorespaces #3\unskip,\ \ignorespaces #1\unskip}%
 }
\else
 \def\@acceptance{\par
  \ifx \@received\empty\else
   \noindent\hfil
   \hbox{\ieej@xkanjiskip{.15\zw}%
    \inhibitglue （\@received\@revised ）\inhibitglue}\par
  \fi}
 \def\received#1#2#3{%
  \gdef\@received{\ignorespaces #1\unskip 年\ignorespaces #2\unskip
   月\ignorespaces #3\unskip 日受付}}
 \def\revised#1#2#3{\gdef\@revised{，\ignorespaces #1\unskip
   年\ignorespaces #2月\unskip \ignorespaces #3\unskip 日再受付}}
\fi

\def\@received{}
\def\@revised{}

\def\maketitle{\par
 \ifnum \chk@alcnt < \@alcnt
  \ieej@warning{information of \string\affiliate\space is not specified}%
 \fi
 \advance \p@alcnt -12\relax
 \ifnum \chk@p@alcnt < \p@alcnt
  \ieej@warning{information of \string\paffiliate\space is not specified}%
 \fi
 \ifnum\@totalnumber=\thr@@
  \Jauthoralign{3}%
 \else
  \ifnum\@totalnumber=4\relax
   \Jauthoralign{2}%
  \fi
 \fi
 %%
  \begingroup
   \long\def\@makefntext##1{\small
     \ifnum \p@alcnt > \@alcnt
      \ifnum \p@alcnt>\thr@@
       \@tempdima=2.5\zw % 2zw
      \else
       \ifnum \p@alcnt=\thr@@
        \@tempdima=2\zw % 1.5zw
       \else
        \@tempdima=1.5\zw % 1zw
       \fi
      \fi
     \else
      \ifnum \@alcnt>\thr@@
       \@tempdima=2.5\zw % 2zw
      \else
       \ifnum \@alcnt=\thr@@
        \@tempdima=2\zw % 1.5zw
       \else
        \@tempdima=1.5\zw % 1zw
       \fi
      \fi
     \fi
     \leftskip\@tempdima
     \leavevmode
     \hbox to \z@{\hss $^{\@thefnmark}$\hskip.25\zw}##1%
   }%
   \if@letter \let\@maketitle\@makelettertitle \fi
   \if@english \let\@maketitle\@makeenglishtitle \fi
   \if@foreword \let\@maketitle\@makeforewordtitle \fi
   \twocolumn[\@maketitle]%
   \thispagestyle{ieej}%
   \if@foreword
    \foot@etitle
   \else
    \@NoteOnArticle
    \@NoteIntConf
    \@mailaddress
    \@affiliate
    \p@affiliate
   \fi
  \endgroup
 \global\let\maketitle\relax
 \global\let\@maketitle\relax
 \global\let\@makelettertitle\relax
 \global\let\@makeenglishtitle\relax
 \global\let\@jtitle\relax
 \global\let\@etitle\relax
 \global\let\foot@etitle\relax
 \global\let\@authorlist\relax
 \global\let\affiliate\relax
 \global\let\paffiliate\relax
 \global\let\@outputJauthorlist\relax
 \global\let\@outputEauthorlist\relax
 \global\let\@outputauthorlist\relax
 \@authorcnt\z@
 \loop\ifnum \@authorcnt < \@totalnumber
  \advance \@authorcnt \@ne
   \global\expandafter\let\csname @authmbrship\number\@authorcnt\endcsname
    \relax
   \global\expandafter\let\csname @Jauthorname\number\@authorcnt\endcsname
    \relax
   \global\expandafter\let\csname @Eauthorname\number\@authorcnt\endcsname
    \relax
 \repeat
 \def\@fnsymbol##1{\ensuremath{\ifcase##1\or
  \dagger\or {\dagger}{\dagger}\or
  {\dagger}{\dagger}{\dagger}\or {\dagger}{\dagger}{\dagger}{\dagger}\or
  \dagger 5\or
  \dagger 6\or 
  \dagger 7\or \dagger 8\or \dagger 9\else\@ctrerr\fi}}%
 \setcounter{footnote}{0}%
}

\def\type@font{\gtfamily\fontsize{18\@JQ}{\z@}\selectfont}
%\def\etitle@font{\fontsize{10.95}{23\@Q}\selectfont}%% 16\@Q
\def\etitle@font{\fontsize{12.1}{23\@Q}\selectfont}%% 16\@Q

\if@letter
 \def\mbrship@font{\small}
 \if@english
  %\font\authorname@font=cmr10 at 10.95pt
  \DeclareRobustCommand\authorname@font{%
   \fontsize{10.95}{\f@baselineskip}\selectfont}
 \else
  \DeclareFixedFont{\KFauthorname}{\kenc@JYn}{mc}{m}{n}{16\@JQ}
  \def\authorname@font{\fontsize{10.95}{\f@baselineskip}\selectfont %% 16\@Q
   \KFauthorname}
 \fi
\else
 \def\mbrship@font{\normalsize}
 \if@english
  %\font\authorname@font=cmr10 at 14.4pt
  \DeclareRobustCommand\authorname@font{%
   \fontsize{14.4}{\f@baselineskip}\selectfont}
 \else
  %\DeclareMathSizes{\@xivpt}{\@xivpt}{\@xpt}{7}%
  %\DeclareMathSizes{\@xivpt}{\@xivpt}{7}{5}%
  \DeclareFixedFont{\KFauthorname}{\kenc@JYn}{mc}{m}{n}{18\@JQ}
  \def\authorname@font{\fontsize{14.4}{\f@baselineskip}\selectfont %% 18\@Q
   \KFauthorname}
 \fi
\fi

\newdimen\abovejtitlesep     \abovejtitlesep\z@
\newdimen\abovejsubtitlesep  \abovejsubtitlesep\z@
\newdimen\abovejauthorsep    \abovejauthorsep\z@
\newdimen\aboveetitlesep     \aboveetitlesep\z@
\newdimen\aboveesubtitlesep  \aboveesubtitlesep\z@
\newdimen\aboveeauthorsep    \aboveeauthorsep\z@
\newdimen\aboveacceptancesep \aboveacceptancesep\z@
\newdimen\aboveabstractsep   \aboveabstractsep\z@
\newdimen\belowkeywordsep    \belowkeywordsep\z@
\newdimen\firstcolumnsep     \firstcolumnsep\z@
\newdimen\secondcolumnsep    \secondcolumnsep\z@

\def\HeadLogo{論\hskip1\zw 文}

%% [paper]
\newdimen\@tempdimc
\newdimen\@tempdimd

\def\@maketitle{%
 \setbox\@tempboxa\hbox{%
  \begin{minipage}{\textwidth}
   \if@feature
    \@tempdima18mm
    \advance \@tempdima .75pt
    \@tempdimb7.5mm
    \advance \@tempdimb .75pt
    \@tempdimc.75pt
    \@tempdimd7.5mm
    \advance \@tempdimd -.75pt
    \hfill\vbox to \@tempdimb{\hrule height \@tempdimc
     \hbox to \@tempdima{%
      \vrule width \@tempdimc height \@tempdimd
       \hss\raise1.85mm\hbox{\gtfamily\fontsize{14}{\z@}\selectfont
        \scalebox{0.85}[1]{特集解説}%
       }\hss
      \vrule width \@tempdimc height \@tempdimd}%
    \hrule height \@tempdimc}%
   \else
    \hfill\vbox to 8.5mm{\hrule height .4mm
     \hbox to 18mm{%
      \vrule width .4mm height 7.5mm
       \hss \raise2.25mm\hbox{\type@font
        \if@comment
         解\hskip1\zw 説%
        \else
         \HeadLogo
        \fi
       }\hss
      \vrule width .4mm height 7.5mm}%
    \hrule height .4mm}%
   \fi
   \hspace*{3.25mm}%
   \vskip3mm
   \vskip\abovejtitlesep
   {\huge\centering
    \leavevmode\inhibitglue\@jtitle\inhibitglue\par
   }%
   \ifx\@jsubtitle\empty\else
    \vskip3mm
    \vskip\abovejsubtitlesep
    {\Large\centering
     \leavevmode\inhibitglue\@jsubtitle\inhibitglue\par
    }%
   \fi
   \vskip24\@Q
   \vskip\abovejauthorsep
   {%
    \baselineskip27\@Q
    \hfil\vbox{%
     \tabskip\z@
     \ifnum\@Jauthoralign=\tw@
      \halign{%
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil\cr
       \@outputJauthorlist
      }%
     \else
      \halign{%
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \hskip\firstcolumnsep
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \hskip\secondcolumnsep
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil\cr
       \@outputJauthorlist\cr
       %%
       \noalign{\vskip-27\@Q}
       \multispan 6 \hfil\@outputtherest\hfil\cr
      }%
     \fi
    }\par
   }%
   \vskip24\@Q
   \vskip\aboveetitlesep
   {\etitle@font
    \hfil\parbox[t]{160mm}{\centering \@etitle}\par
   }%
   \ifx\@esubtitle\empty\else
    \vskip2.5mm
    \vskip\aboveesubtitlesep
    \hfil\parbox[t]{160mm}{\normalsize\centering \@esubtitle}\par
   \fi
   \vskip11\@Q
   \vskip\aboveeauthorsep
   {\normalsize\normalfont
    \leftskip3\zw\rightskip3\zw
    \centering
    \@outputEauthorlist\par
   }%
   \vskip\baselineskip
   \vskip\aboveacceptancesep
   {\small
    \@acceptance\par
   }%
   \vskip20\@Q
   \vskip\aboveabstractsep
   \ifvoid\@abstractbox\else
    \hfil\box\@abstractbox\par
    \vskip4\@Q
    \vskip\baselineskip
   \fi
   \ifvoid\j@keywordbox\else
    \hfil\box\j@keywordbox\par
    \nointerlineskip
    \vskip8.5\@Q
   \fi
   \ifvoid\e@keywordbox\else
    \hfil\box\e@keywordbox
   \fi
  \end{minipage}%
 }%
  \@tempdima\ht\@tempboxa
  \advance \@tempdima \dp\@tempboxa
  \divide \@tempdima \Cvs
  \@tempcnta=\@tempdima
  \advance \@tempcnta \tw@
  {\newpage\null
   \boxmaxdepth\z@
   \lineskiplimit\z@
   \lineskip\z@
   \parindent\z@
   \vbox to \@tempcnta\Cvs{%
    \leavevmode\box\@tempboxa
   \vss}%
  }\par
  \vspace{\belowkeywordsep}%
}

\def\typel@font{\gtfamily\fontsize{14\@JQ}{\Cvs}\selectfont}

%% [letter]
\def\@makelettertitle{%
 \setbox\@tempboxa\hbox{%
  \begin{minipage}{\textwidth}
   \hfill\vbox to 8.5mm{\hrule height .4mm
    \hbox to 18mm{%
     \vrule width .4mm height 7.5mm
      \hss
       \vbox{\vss
        \hbox to 17mm{\hss
         \parbox[b]{14.15mm}{\typel@font 研究開発\\[-1.5mm]
          \kintou{4\zw}{レター}}%
        \hss}%
       \vss}%
      \hss
     \vrule width .4mm height 7.5mm}%
   \hrule height .4mm}\hspace*{3.25mm}%
   \vskip4mm
   \vskip\abovejtitlesep
   {\LARGE\centering
    \leavevmode\inhibitglue\@jtitle\inhibitglue\par
   }%
   \ifx\@jsubtitle\empty\else
    \vskip2mm
    \vskip\abovejsubtitlesep
    {\Large\centering
     \leavevmode\inhibitglue\@jsubtitle\inhibitglue\par
    }%
   \fi
   \vskip20\@Q
   \vskip\abovejauthorsep
   {%
    \baselineskip22\@Q
    \hfil\vbox{%
     \tabskip\z@
     \ifnum\@Jauthoralign=\tw@
      \halign{%
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil\cr
       \@outputJauthorlist
      }%
     \else
      \halign{%
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \hskip\firstcolumnsep
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \hskip\secondcolumnsep
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil\cr
       \@outputJauthorlist\cr
       %%
       \noalign{\vskip-22\@Q}
       \multispan 6 \hfil\@outputtherest\hfil\cr
      }%
     \fi
    }\par
   }%
   \vskip16\@Q
   \vskip\aboveetitlesep
   {\etitle@font
    \hfil\parbox[t]{160mm}{\centering \@etitle}\par
   }%
   \ifx\@esubtitle\empty\else
    \vskip.5mm
    \vskip\aboveesubtitlesep
    \hfil\parbox[t]{160mm}{\normalsize\centering \@esubtitle}\par
   \fi
   \vskip12\@Q
   \vskip\aboveeauthorsep
   {\normalsize\normalfont
    \leftskip3\zw\rightskip3\zw
    \centering
    \@outputEauthorlist\par
   }%
   \vskip\baselineskip
   \vskip\aboveacceptancesep
   {\small
    \@acceptance\par
   }%
   %\vskip33\@Q
   \vskip20\@Q
   \vskip\aboveabstractsep
   \ifvoid\@abstractbox\else
    \hfil\box\@abstractbox\par
    \vskip4\@Q
    \vskip\baselineskip
   \fi
   \ifvoid\j@keywordbox\else
    \hfil\box\j@keywordbox\par
    \nointerlineskip
    \vskip8.5\@Q
   \fi
   \ifvoid\e@keywordbox\else
    \hfil\box\e@keywordbox
   \fi
  \end{minipage}%
 }%
  \@tempdima\ht\@tempboxa
  \advance \@tempdima \dp\@tempboxa
  \divide \@tempdima \Cvs
  \@tempcnta=\@tempdima
  \advance \@tempcnta \tw@
  {\newpage\null
   \boxmaxdepth\z@
   \lineskiplimit\z@
   \lineskip\z@
   \parindent\z@
   \vbox to \@tempcnta\Cvs{%
    \leavevmode\box\@tempboxa
   \vss}%
  }\par
  \vspace{\belowkeywordsep}%
}

\def\fieldDen@YEAR#1{%
 \afterassignment\remove@to@nnil
  \count@ 0#1\relax\@nnil
 \ifnum\count@=\z@\else
  \@tempcnta=#1\relax
  \advance \@tempcnta -131\relax
  \xdef\@VOL{\the\@tempcnta}%
 \fi
}

%% [english] and [letter,english]
\def\@makeenglishtitle{%
 \if@fieldDen
  \fieldDen@YEAR{\@VOL}%
  \pagestyle{IEEJ}%
 \fi
 %%
 \setbox\@tempboxa\hbox{%
  \begin{minipage}{\textwidth}
   \hfill\vbox to 8.5mm{\hrule height .4mm
    \hbox to 18mm{%
     \vrule width .4mm height 7.5mm
      \hss\raise2.25mm\hbox{\LARGE\bfseries\if@letter Letter\else Paper\fi}\hss
     \vrule width .4mm height 7.5mm}%
   \hrule height .4mm}\hspace*{3.25mm}%
   \vskip3mm
   \vskip\aboveetitlesep
   {\if@letter \LARGE\else \huge\fi
    \centering
    \leavevmode\inhibitglue\@jtitle\inhibitglue\par
   }%
   \ifx\@jsubtitle\empty\else
    \vskip2mm
    \vskip\aboveesubtitlesep
    {\if@letter \Large\else \LARGE\fi
     \centering
     \leavevmode\inhibitglue\@jsubtitle\inhibitglue\par
    }%
   \fi
   \vskip24\@Q
   \vskip\aboveeauthorsep
   {\baselineskip23\@Q
    \hfil\vbox{%
    \tabskip\z@
    \ifnum\@Eauthoralign=\@ne
     \halign{%
      ##\hfil & \hskip1em ##\hfil\cr
      \@outputauthorlist
     }%
    \else
     \ifnum\@totalnumber=\@ne
      \halign{%
       ##\hfil & \hskip1em ##\hfil\cr
       \@outputauthorlist
      }%
     \else
      \halign{%
       ##\hfil & ##\hfil
	& \hskip\firstcolumnsep\hskip1.5em ##\hfil & ##\hfil\cr
       \@outputauthorlist\cr
       \noalign{\vskip-23\@Q}
       \ifodd\@totalnumber\else
	\noalign{\vskip-23\@Q}
       \fi
       \multispan 4 \hfil \@outputEtherest\hfil\cr
      }%
     \fi
    \fi
    }\par
   }%
   \vskip\baselineskip
   \vskip\aboveacceptancesep
   {\small
    \@acceptance\par
   }%
   \vskip24\@Q
   \vskip\aboveabstractsep
   \ifvoid\@abstractbox\else
    \hfil\box\@abstractbox\par
    \vskip4\@Q
    \vskip\baselineskip
   \fi
   \ifvoid\e@keywordbox\else
    \hfil\box\e@keywordbox
   \fi
  \end{minipage}%
 }%
  \@tempdima\ht\@tempboxa
  \advance \@tempdima \dp\@tempboxa
  \divide \@tempdima \Cvs
  \@tempcnta=\@tempdima
  \advance \@tempcnta \tw@
  {\newpage\null
   \boxmaxdepth\z@
   \lineskiplimit\z@
   \lineskip\z@
   \parindent\z@
   \vbox to \@tempcnta\Cvs{%
    \leavevmode\box\@tempboxa
   \vss}%
  }\par
  \vspace{\belowkeywordsep}%
}

%% [foreword]
\if@foreword
 \DeclareFixedFont{\KFfwtitle}{\kenc@JYn}{mc}{m}{n}{23\@JQ}
 \DeclareFixedFont{\KFauthorname}{\kenc@JYn}{mc}{m}{n}{17\@JQ}
 \def\authorname@font{\KFauthorname}
\fi

\def\foreword@Logo{%
 \smash{\lower12mm\hbox to \z@{\hss
  \vbox to 8.5mm{\hrule height .4mm
    \@tempdima18mm
    \hbox to \@tempdima{%
     \vrule width .4mm height 7.5mm
      \hss \raise2.25mm\hbox{\type@font
       巻頭言%
      }\hss
     \vrule width .4mm height 7.5mm}%
  \hrule height .4mm}\hspace*{3.25mm}%
 }}%
}

\def\@makeforewordtitle{%
 \setbox\@tempboxa\hbox{%
  \begin{minipage}{\textwidth}
   \vskip-\headsep
   \vskip1mm
   \leavevmode
   \hbox to \textwidth{{\color{LXXgray}\leaders \hrule \@height 3mm\hfill}%
    \foreword@Logo
   }\par
   \nointerlineskip
   \vskip5mm
   \vskip\abovejtitlesep
   {\huge\KFfwtitle
    \leftskip6.5mm
    \rightskip6.5mm
    \leavevmode\inhibitglue\@jtitle\inhibitglue\par
   }%
   %%\ifx\@jsubtitle\empty\else
   %% \vskip3mm
   %% {\Large
   %%  \@jsubtitle\par
   %% }%
   %%\fi
   \vskip30\@Q
   \vskip\abovejauthorsep
   {%
    \leftskip6.5mm
    \rightskip6.5mm
    \baselineskip27\@Q
    \hfill\vbox{%
     \tabskip\z@
     \ifnum\@Jauthoralign=\tw@
      \halign{%
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil &
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil\cr
       \@outputJauthorlist
      }%
     \else
      \halign{%
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil & 
       \authorname@font\hskip1\zw
       \mbrship@font ##\unskip
	& \hskip1\zw\lower.1\zh\hbox{\authorname@font ##}\hfil\cr
       \@outputJauthorlist\cr
       %%
       \noalign{\vskip-27\@Q}
       \multispan 6 \hfil\@outputtherest\hfil\cr
      }%
     \fi
    }\par
   }%
   \ifx\@received\empty
    \vskip32\@Q
   \else
    \vskip\baselineskip
    \vskip\aboveacceptancesep
    {\small
     \@acceptance\par
    }%
    \vskip20\@Q
   \fi
   \vskip\aboveabstractsep
   \ifvoid\@abstractbox\else
    \hfil\box\@abstractbox\par
    \vskip4\@Q
    \vskip\baselineskip
   \fi
   \ifvoid\j@keywordbox\else
    \hfil\box\j@keywordbox\par
    \nointerlineskip
    \vskip8.5\@Q
   \fi
   \ifvoid\e@keywordbox\else
    \hfil\box\e@keywordbox
   \fi
  \end{minipage}%
 }%
  \@tempdima\ht\@tempboxa
  \advance \@tempdima \dp\@tempboxa
  \divide \@tempdima \Cvs
  \@tempcnta=\@tempdima
  \advance \@tempcnta \tw@
  {\newpage\null
   \boxmaxdepth\z@
   \lineskiplimit\z@
   \lineskip\z@
   \parindent\z@
   \vbox to \@tempcnta\Cvs{%
    \leavevmode\box\@tempboxa
   \vss}%
  }\par
  \vspace{\belowkeywordsep}%
}

%% [ExtendedSummary]
%\def\makeExSumtitle{\par
% \begingroup
%  \twocolumn[\@makeExSumtitle]
%  \thispagestyle{exsum}
% \endgroup
% \pagestyle{exsum}
% \global\let\makeExSumtitle\relax
% \global\let\@makeExSumtitle\relax
%}

%\if@ExSum
% \let\maketitle\makeExSumtitle
%\fi

%\def\exsumarraystretch#1{\gdef\@exsumarraystretch{#1}}
%\def\@exsumarraystretch{}
%\exsumarraystretch{1.8}

%\def\@makeExSumtitle{%
% \setbox\@tempboxa\hbox{%
%  \begin{minipage}{\textwidth}
%   \vskip6.5mm
%   \vskip\abovejtitlesep
%   {\huge\centering
%    \leavevmode\inhibitglue\@jtitle\inhibitglue\par
%   }%
%   \ifx\@jsubtitle\empty\else
%    \vskip2mm
%    \vskip\abovejsubtitlesep
%    {\Large\centering
%     \leavevmode\inhibitglue\@jsubtitle\inhibitglue\par
%    }%
%   \fi
%   \vskip1.5\baselineskip
%   \vskip\abovejauthorsep
%   {\def\arraystretch{\@exsumarraystretch}%
%    \hfil
%    \begin{tabular}{@{}l@{}}
%     \@outputExSum@authorlist
%    \end{tabular}%
%   }%
%   \vskip2\baselineskip
%   \vskip\aboveabstractsep
%   \ifvoid\e@keywordbox\else
%    \hfil\box\e@keywordbox
%   \fi
%  \end{minipage}%
% }%
%  \small\baselineskip16\@Q
%  \@tempdima \ht\@tempboxa
%  \advance \@tempdima \dp\@tempboxa
%  \@tempdimb \@tempdima
%  \@tempdimc \@tempdima
%  \divide \@tempdimc \baselineskip
%  \@tempcnta=\@tempdimc
%  \@tempdimc \@tempcnta\baselineskip
%  \advance \@tempdimb -\@tempdimc
%  \ifdim \@tempdimb > .5\baselineskip
%   \advance \@tempcnta \tw@
%  \else
%   \advance \@tempcnta \@ne
%  \fi
%  {\newpage\null
%   \boxmaxdepth\z@
%   \lineskiplimit\z@
%   \lineskip\z@
%   \parindent\z@
%   \vbox to \@tempcnta\baselineskip{%
%    \leavevmode\box\@tempboxa\par
%   \vss}%
%  }\par
%  \vspace{\belowkeywordsep}%
%}

%\if@ExSum
%\def\ExSum@shortstack{\@ifnextchar[\@ExSum@shortstack{\@ieej@shortstack[c]}}
%\def\@ExSum@shortstack[#1]{%
%  \leavevmode
%  \vtop\bgroup
%    \let\mb@l\hss\let\mb@r\hss
%    \expandafter\let\csname mb@#1\endcsname\relax
%    \let\\\@stackcr
%    \@ishortstack}
%
%\def\NE@EaeNP#1#2#3{%
% \@tempcnta\z@
% \advance \@authorcnt \@ne
% %% author's name in English
% \@temptokena{#1}%
% \expandafter\protected@xdef\csname @Eauthorname\number\@authorcnt\endcsname{%
%  {\noexpand\authorname@font
%   \the\@temptokena\hskip1em
%   \csname #2@member\endcsname\hskip1em}%
%   \noexpand\small
%   (\noexpand\ExSum@shortstack[l]{%
%    \ignorespaces\csname ExSumAffi@#3\endcsname\unskip)}}%
% \global\@totalnumber\@authorcnt
%}
%
%\def\authorname@font{\fontsize{12}{\f@baselineskip}\selectfont}
%
%\def\affiliate[#1]#2{%
% \expandafter\gdef\csname ExSumAffi@#1\endcsname{#2}%
%}
%\fi

%\def\@outputExSum@authorlist{%
% \gdef\m@member{Member}%
% \gdef\n@member{Non-member}%
% \gdef\a@member{Associate Member}%
% \gdef\l@member{Life Member}%
% \gdef\s@member{Student Member}%
% \gdef\h@member{Honorary Member}%
% \gdef\S@member{Senior Member}%
% \gdef\f@member{Fellow}%
% \@authorcnt\z@
% \process@ExSum@authorlist
%}

%\def\process@ExSum@authorlist{%
% \global\advance \@authorcnt \@ne
% \csname @Eauthorname\number\@authorcnt\endcsname\\
% \ifnum\@authorcnt < \@totalnumber \expandafter\process@ExSum@authorlist\fi
%}

\newif\if@fieldDen \@fieldDenfalse

\def\FIELD#1{\def\@tempx{#1}%
 \ifx \@tempx\empty
  \gdef\@FIELD{X}%
  \gdef\e@FIELD{XX}%
 \else
  \gdef\@FIELD{#1}%
  \if#1A\gdef\e@FIELD{FM}\else
   \if#1B\gdef\e@FIELD{PE}\else
    \if#1C\gdef\e@FIELD{EIS}\else
     \if#1D\gdef\e@FIELD{IA}\if@english\global\@fieldDentrue\fi\else
      \if#1E\gdef\e@FIELD{SM}\else
       \gdef\e@FIELD{#1}%
       \fi
      \fi
     \fi
    \fi
   \fi
 \fi
}

\def\NO#1{%
 \def\@tempa{#1}%
 \ifx\@tempa\empty
  \gdef\@NO{xx}%
 \else
  \edef\@tempb{\zap@space#1 \@empty}%
  \afterassignment\remove@to@nnil
  \count@ 0\@tempb\relax\@nnil
  \ifnum\count@=\z@
   \gdef\@NO{xx}%
  \else
   \gdef\@NO{\zap@space#1 \@empty}%
  \fi
 \fi
}

\def\YEAR#1{%
 \def\@tempa{#1}%
 \ifx\@tempa\empty
  \gdef\f@YEAR{202x}%
 \else
  \edef\@tempb{\zap@space#1 \@empty}%
  \afterassignment\remove@to@nnil
  \count@ 0\@tempb\relax\@nnil
  \ifnum\count@=\z@
   \xdef\f@YEAR{202x}%
  \else
   \xdef\f@YEAR{\@tempb}%
   \@tempcnta=#1\relax
   \advance \@tempcnta -1880\relax
   \xdef\@VOL{\the\@tempcnta}%
  \fi
 \fi
}

\def\@FIELD{X}
\def\e@FIELD{XX}
\def\@VOL{xxx}
\def\@NO{xx}
\def\f@YEAR{xxxx}

\setcounter{secnumdepth}{3}
%\newcounter{part}
\newcounter{section}
\newcounter{subsection}[section]
\newcounter{subsubsection}[subsection]
\newcounter{paragraph}[subsubsection]
\newcounter{subparagraph}[paragraph]
%\renewcommand{\thepart}{\@Roman\c@part}
\renewcommand{\thesection}{\@arabic\c@section}
\if@english
 \renewcommand{\thesubsection}{\thesection.\@arabic\c@subsection}
 \renewcommand{\thesubsubsection}{\thesubsection.\@arabic\c@subsubsection}
\else
 %%%%%%%%%%%%\ifx\directlua\@undefined
 \def\thesubsection{\protect\leavevmode
  \inhibitglue 〈\thesection\hbox to .5\zw{\hss ・\hss}%
  \@arabic\c@subsection 〉\inhibitglue}
 \def\thesubsubsection{\protect\leavevmode
  \inhibitglue 〈\thesection\hbox to .5\zw{\hss ・\hss}%
  \@arabic\c@subsection\hbox to .5\zw{\hss ・\hss}%
  \@arabic\c@subsubsection 〉\inhibitglue}
\fi
\renewcommand{\theparagraph}{\@arabic\c@paragraph}
\renewcommand{\thesubparagraph}{\@arabic\c@subparagraph}

\def\@afterheading{%
 \global\@nobreaktrue
 \everypar{%
  \if@nobreak
   \global\@nobreakfalse
   \clubpenalty \z@
    \if@afterindent
    \else
     {\setbox\z@=\lastbox}%
    \fi
  \else
   \clubpenalty\@clubpenalty
   \everypar{}%
  \fi}%
}

%% \@startsection{NAME}{LEVEL}{INDENT}{BEFORESKIP}{AFTERSKIP}{STYLE}
\def\@startsection#1#2#3#4#5#6{\if@noskipsec \leavevmode \fi
   \par \@tempskipa #4\relax
   \@afterindenttrue
   \ifdim \@tempskipa <\z@ \@tempskipa -\@tempskipa \@afterindentfalse\fi
   \if@nobreak
    \everypar{}%
   \else
    %\addpenalty\@secpenalty
    \vskip-\prevdepth \prevdepth\z@ \vskip\Cvs
    \advance\@tempskipa-\Cvs
    \vspace*{\@tempskipa}
    %\addvspace\@tempskipa
   \fi
 \@ifstar{\@ssect{#3}{#4}{#5}{#6}}{\@dblarg{\@sect{#1}{#2}{#3}{#4}{#5}{#6}}}}

\def\sectionnum@font{\sffamily\fontsize{14\@Q}{\z@}\selectfont}
\def\subsectionnum@font{\sffamily\normalsize}
\def\dotafter@section{.}

\newif\ifjidori
\if@english\jidorifalse\else\jidoritrue\fi

%% \@sect{NAME}{LEVEL}{INDENT}{BEFORESKIP}{AFTERSKIP}{STYLE}[ARG1]{ARG2}
%% \ifdim \@tempskipa>\z@ --> \ifdim \@tempskipa<\z@
\def\@sect#1#2#3#4#5#6[#7]#8{%
 \ifnum #2>\c@secnumdepth
  \let\@svsec\@empty
 \else
  \refstepcounter{#1}%
  %\protected@edef\@svsec{\@seccntformat{#1}\relax}%
  \ifnum#2=\@ne
   \if@letter
    \protected@edef\@svsec{%
     {\csname sub#1num@font\endcsname\csname the#1\endcsname
      \csname dotafter@#1\endcsname\hskip1\zw}}%
   \else
    \protected@edef\@svsec{%
     {\csname #1num@font\endcsname\csname the#1\endcsname
      \csname dotafter@#1\endcsname\hskip1\zw}}%
   \fi
  \else
   \protected@edef\@svsec{%
    {\noexpand\subsectionnum@font\noexpand\gtfamily
     \csname the#1\endcsname\hskip1\zw}}%
  \fi
 \fi
  \@tempskipa #5\relax
  \ifdim \@tempskipa<\z@
   \ifjidori
    \setbox\@tempboxa\hbox{\inhibitglue\ignorespaces #8\inhibitglue}%
    \ifdim \wd\@tempboxa < 4\zw
     \def\@svsechd{#6{\hskip #3\relax \@svsec
      \kintou{4\zw}{\inhibitglue\ignorespaces #8\inhibitglue}}}%
    \else
     \def\@svsechd{#6{\hskip #3\relax \@svsec
      \inhibitglue\ignorespaces #8\inhibitglue}}%
    \fi
   \else
    \def\@svsechd{#6{\hskip #3\relax \@svsec
     \inhibitglue\ignorespaces #8\inhibitglue}}%
   \fi
  \else
   \begingroup
    #6{%
     \ifjidori
      %\ifnum#2=\@ne\@tempdimb5\zw\else\@tempdimb4\zw\fi
      \@tempdimb4\zw
      \setbox\@tempboxa\hbox{\inhibitglue\ignorespaces #8\inhibitglue}%
      \ifdim \wd\@tempboxa < \@tempdimb
       \@hangfrom{\hskip #3\relax\@svsec}%
        \interlinepenalty\@M
        \kintou{\@tempdimb}{\inhibitglue\ignorespaces #8\inhibitglue}\@@par
      \else
       \@hangfrom{\hskip #3\relax\@svsec}\interlinepenalty\@M
         \inhibitglue\ignorespaces #8\inhibitglue\@@par
      \fi
     \else
      \@hangfrom{\hskip #3\relax\@svsec}\interlinepenalty\@M
       \inhibitglue\ignorespaces #8\inhibitglue\@@par
     \fi
      }%
   \endgroup
  \fi
  \@xsect{#5}}

%% \@ssect{INDENT}{BEFORESKIP}{AFTERSKIP}{STYLE}{ARG} ==
%% \ifdim \@tempskipa>\z@ --> \ifdim \@tempskipa<\z@
\def\@ssect#1#2#3#4#5{%
  \@tempskipa #3\relax
  \ifdim \@tempskipa<\z@
   \ifjidori
    \setbox\@tempboxa\hbox{\inhibitglue\ignorespaces #5\inhibitglue}%
    \ifdim \wd\@tempboxa < 4\zw
     \def\@svsechd{#4{\hskip#1\relax
      \kintou{4\zw}{\inhibitglue\ignorespaces #5\inhibitglue}}}%
    \else
     \def\@svsechd{#4{\hskip#1\relax\inhibitglue\ignorespaces #5\inhibitglue}}%
    \fi
   \else
    \def\@svsechd{#4{\hskip#1\relax\inhibitglue\ignorespaces #5\inhibitglue}}%
   \fi
  \else
   \begingroup
    #4{%
    \ifjidori
     %\ifdim\@tempskipa<.5\Cvs \@tempdimb 4\zw\else\@tempdimb5\zw\fi
     \@tempdimb4\zw
     \setbox\@tempboxa\hbox{\inhibitglue\ignorespaces #5\inhibitglue}%
     \ifdim \wd\@tempboxa < \@tempdimb
      \@hangfrom{\hskip #1}\interlinepenalty\@M
       \kintou{\@tempdimb}{\inhibitglue\ignorespaces #5\inhibitglue}\@@par
     \else
      \@hangfrom{\hskip #1}\interlinepenalty\@M
       \inhibitglue\ignorespaces #5\inhibitglue\@@par
     \fi
    \else
     \@hangfrom{\hskip #1}\interlinepenalty\@M
      \inhibitglue\ignorespaces #5\inhibitglue\@@par
    \fi
    }%
   \endgroup
  \fi
 \@xsect{#3}}

%% \ifdim \@tempskipa>\z@ --> \ifdim \@tempskipa<\z@
\def\@xsect#1{%
  \@tempskipa #1\relax
  \ifdim \@tempskipa<\z@
    \@nobreakfalse
    \global\@noskipsectrue
    \everypar{%
      \if@noskipsec
        \global\@noskipsecfalse
       {\setbox\z@\lastbox}%
        \clubpenalty\@M
        \begingroup \@svsechd \endgroup
        \unskip
        \@tempskipa #1\relax
        %\hskip -\@tempskipa
        \hskip -.5\@tempskipa
        \hspace*{-.5\@tempskipa \@plus .25\zw \@minus .25\zw}%
        \pagebreak[2]%
      \else
        \clubpenalty \@clubpenalty
        \everypar{}%
      \fi}%
  \else
    \par \nobreak
    \vskip \@tempskipa
    \@afterheading
  \fi
  \ignorespaces}

%%\def\@seccntformat#1{\csname the#1\endcsname\hskip1\zw}

\DeclareFixedFont{\KFsec}{\kenc@JYn}{gt}{m}{n}{14\@JQ}
\def\sec@font{\bfseries\fontsize{10.95}{\Cvs}\selectfont\KFsec}

\if@letter
 \newcommand{\section}{\@startsection{section}{1}{1\zw}%
   {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
   {\z@ \@plus.1\Cdp \@minus.1\Cdp}%
   {\reset@font\normalsize\bfseries\mathversion{bold}}}
\else
 \newcommand{\section}{\@startsection{section}{1}{1\zw}%
   {.5\Cvs \@plus.3\Cdp \@minus.2\Cdp}%
   {.5\Cvs \@plus.3\Cdp \@minus.2\Cdp}%
   {\reset@font\sec@font\mathversion{bold}}}
\fi
%\if@ExSum
%\DeclareFixedFont{\KFsec}{\kenc@JYn}{gt}{m}{n}{13\@JQ}
%\def\sec@font{\bfseries\fontsize{10}{\Cvs}\selectfont\KFsec}
%\renewcommand{\section}{\@startsection{section}{1}{1\zw}%
%  {\z@ \@plus.3\Cdp \@minus.2\Cdp}%
%  {\z@ \@plus.3\Cdp \@minus.2\Cdp}%
%  {\reset@font\sec@font\mathversion{bold}}}
%\fi
\newcommand{\subsection}{\@startsection{subsection}{2}{1\zw}%
  {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
  {-2\zw \@plus-.25\zw \@minus-.25\zw}%
  {\reset@font\normalsize\bfseries\mathversion{bold}}}
\newcommand{\subsubsection}{\@startsection{subsubsection}{3}{1\zw}%
  {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
  {-2\zw}%
  {\reset@font\normalsize\bfseries\mathversion{bold}}}
\newcommand{\paragraph}{\@startsection{paragraph}{4}{1\zw}%
   {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
   {-2\zw}%
   {\reset@font\normalsize}}
\newcommand{\subparagraph}{\@startsection{subparagraph}{5}{1\zw}%
   {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
   {-2\zw}%
   {\reset@font\normalsize}}

\newcommand{\appendix}{\par %}{
 \if@letter
  \renewcommand{\section}{\@startsection{section}{1}{\z@}%
    {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
    {\z@ \@plus.1\Cdp \@minus.1\Cdp}%
    {\reset@font\normalsize\bfseries\mathversion{bold}}}%
 \else
  \renewcommand{\section}{\@startsection{section}{1}{\z@}%
    {.5\Cvs \@plus.3\Cdp \@minus.2\Cdp}%
    {.5\Cvs \@plus.3\Cdp \@minus.2\Cdp}%
    {\reset@font\sec@font\mathversion{bold}}}%
 \fi
 \if@english
  \section*{\centering Appendix}
 \else
  \section*{\centering 付\hskip2\zw 録}
 \fi
 \renewcommand{\section}{\@startsection{section}{1}{1\zw}%
   {\z@ \@plus.2\Cdp \@minus.1\Cdp}%
   {\z@ \@plus.1\Cdp \@minus.1\Cdp}%
   {\reset@font\normalsize\bfseries\mathversion{bold}}}%
 \setcounter{section}{0}%
 \setcounter{subsection}{0}%
 \setcounter{equation}{0}%
 \setcounter{figure}{0}%
 \setcounter{table}{0}%
 \if@english
  \def\theequation{A\arabic{equation}}%
 \else
  \def\theequation{\protect\mbox{付}\arabic{equation}}%
  \if@ecaption
   \def\fnum@figure{付図\thefigure}%
   \def\fnum@table{付表\thetable}%
  \fi
 \fi
 \if@ecaption
  \def\fnum@efigure{app.\protect\,Fig.\protect\,\thefigure.}%
  \def\fnum@etable{app.\protect\,Table~\thetable.}%
 \else
  \def\fnum@figure{app.\protect\,Fig.\protect\,\thefigure.}%
  \def\fnum@table{app.\protect\,Table~\thetable.}%
 \fi
}

\if@twocolumn
  \setlength\leftmargini {2\zw}
\else
  \setlength\leftmargini {2\zw}
\fi
\setlength\leftmarginii  {2\zw}
\setlength\leftmarginiii {2\zw}
\setlength\leftmarginiv  {2\zw}
\if@twocolumn
  \setlength\leftmarginv {1\zw}
  \setlength\leftmarginvi{1\zw}
\else
  \setlength\leftmarginv {1\zw}
  \setlength\leftmarginvi{1\zw}
\fi
\setlength  \labelsep  {1\zw}
\setlength  \labelwidth{\leftmargini}
\addtolength\labelwidth{-\labelsep}
\@beginparpenalty\z@ % -\@lowpenalty
\@endparpenalty\z@ %   -\@lowpenalty
\@itempenalty\z@ %     -\@lowpenalty

%% from latex.ltx
\def\@item[#1]{%
  \if@noparitem
    \@donoparitem
  \else
    \if@inlabel
      \indent \par
    \fi
    \ifhmode
      \unskip\unskip \par
    \fi
    \if@newlist
      \if@nobreak
        \@nbitem
      \else
        \addpenalty\@beginparpenalty
        \addvspace\@topsep
        \addvspace{-\parskip}%
      \fi
    \else
      \addpenalty\@itempenalty
      \addvspace\itemsep
    \fi
    \global\@inlabeltrue
  \fi
  \everypar{%
    \@minipagefalse
    \global\@newlistfalse
    \if@inlabel
      \global\@inlabelfalse
      {\setbox\z@\lastbox
       \ifvoid\z@
         \kern-\itemindent
       \fi}%
      \box\@labels
      \penalty\z@
    \fi
    \if@nobreak
      \@nobreakfalse
      \clubpenalty\z@ % \@M --> \z@
    \else
      \clubpenalty \@clubpenalty
      \everypar{}%
    \fi}%
  \if@noitemarg
    \@noitemargfalse
    \if@nmbrlist
      \refstepcounter\@listctr
    \fi
  \fi
  \sbox\@tempboxa{\makelabel{#1}}%
  \global\setbox\@labels\hbox{%
    \unhbox\@labels
    \hskip \itemindent
    \hskip -\labelwidth
    \hskip -\labelsep
    \ifdim \wd\@tempboxa >\labelwidth
      \box\@tempboxa
    \else
      \hbox to\labelwidth {\unhbox\@tempboxa}%
    \fi
    \hskip \labelsep}%
  \ignorespaces\inhibitglue
}

\renewcommand{\theenumi}{\@arabic\c@enumi}
\renewcommand{\theenumii}{\@alph\c@enumii}
\renewcommand{\theenumiii}{\@roman\c@enumiii}
\renewcommand{\theenumiv}{\@Alph\c@enumiv}
%\newcommand{\labelenumi}{\theenumi.}
%\newcommand{\labelenumii}{(\theenumii)}
\newcommand{\labelenumiii}{\theenumiii.}
\newcommand{\labelenumiv}{\theenumiv.}
\renewcommand{\p@enumii}{\theenumi}
\renewcommand{\p@enumiii}{\theenumi(\theenumii)}
\renewcommand{\p@enumiv}{\p@enumiii\theenumiii}
\if@english
 \def\labelenumi{(\,\theenumi\,)}
\else
 \def\labelenumi{\leavevmode\inhibitglue （\,\theenumi\,）\inhibitglue}
\fi
\if@english
 \def\labelenumii{(\,\theenumii\,)}
\else
 \def\labelenumii{\leavevmode\inhibitglue （\,\theenumii\,）\inhibitglue}
\fi

\renewenvironment{enumerate}
  {\ifnum \@enumdepth >3\relax\@toodeep\else
   \advance\@enumdepth\@ne
   \edef\@enumctr{enum\romannumeral\the\@enumdepth}%
   \list{\csname label\@enumctr\endcsname}{%
         \topsep\z@\parsep\z@\partopsep\z@\itemsep\z@
	 \leftmargin3\zw
	 \labelwidth2\zw
	 \labelsep1\zw
	 \itemindent1\zw
	 \listparindent1\zw
         \clubpenalty\z@
         \widowpenalty\z@
         \@itempenalty\z@
         \usecounter{\@enumctr}%
         \def\makelabel##1{\hss\llap{##1}}}%
   \fi}{\endlist}

\newcommand{\labelitemi}{\leavevmode
 \raise.1\zh\hbox to 1\zw{\hss\textbullet\hss}}
\newcommand{\labelitemii}{\leavevmode
 \raise.1\zh\hbox to 1\zw{\hss $\circ$\hss}}
\newcommand{\labelitemiii}{\leavevmode
 \raise.1\zh\hbox to 1\zw{\hss $\star$\hss}}
\newcommand{\labelitemiv}{\leavevmode
 \raise.1\zh\hbox to 1\zw{\hss \textasteriskcentered\hss}}

\renewenvironment{itemize}
  {\ifnum \@itemdepth >3\relax\@toodeep\else
   \advance\@itemdepth\@ne
   \edef\@itemitem{labelitem\romannumeral\the\@itemdepth}%
   \expandafter
   \list{\csname \@itemitem\endcsname}{%
	 \topsep\z@\parsep\z@\partopsep\z@\itemsep\z@
	 \leftmargin2\zw
	 \labelwidth1\zw
	 \labelsep\z@ %% \itemindent
	 \listparindent1\zw
         \clubpenalty\z@
         \widowpenalty\z@
         \@itempenalty\z@
         \def\makelabel##1{\leavevmode\hbox to 1\zw{\hss ##1\hss}}%
   }%
   \fi}{\endlist}

\def\descriptionlabel#1{%
  \setbox0\hbox{\bfseries #1}%
  \dimen0=\wd0 \dimen1=1\zw
  \divide \dimen0 \dimen1
  \multiply \dimen0 \dimen1
  \ifdim\dimen0<\wd0 \advance \dimen0 \dimen1\fi
  \hbox to \dimen0{\box0 \hfil}\hfil}

\def\description{\list{}{%
  \leftmargin1\zw
  \labelwidth\leftmargin
  \labelsep1\zw
  \listparindent1\zw
  \advance \labelwidth -\labelsep
  \let\makelabel\descriptionlabel
  \topsep\z@\parsep\z@\partopsep\z@\itemsep\z@}}
\let\enddescription\endlist

\newskip\@hlskip
\@hlskip=.5\baselineskip \@plus 1mm \@minus .5mm

\newenvironment{verse}
  {\let\\\@centercr
   \list{}{\itemsep\z@
           \topsep\@hlskip\parsep\z@\partopsep\z@
           \itemindent -1\zw
           \listparindent\itemindent
           \rightmargin\leftmargin \advance\leftmargin 1\zw}%
           \item\relax}{\endlist}

\newenvironment{quotation}
  {\list{}{\listparindent 1\zw
           \itemindent\listparindent
           \rightmargin\leftmargin
           \topsep\@hlskip\parsep\z@\partopsep\z@
           }%
           \item\relax}{\endlist}

\newenvironment{quote}
  {\list{}{%
           \topsep\@hlskip\parsep\z@\partopsep\z@
           \rightmargin\leftmargin}%
           \item\relax}{\endlist}

\gdef\tabbing{\lineskip \z@skip\let\>\@rtab\let\<\@ltab\let\=\@settab
     \let\+\@tabplus\let\-\@tabminus\let\`\@tabrj\let\'\@tablab
     \let\\=\@tabcr
     \@hightab\@firsttab
     \global\@nxttabmar\@firsttab
     \dimen\@firsttab\@totalleftmargin
     \global\@tabpush\z@ \global\@rjfieldfalse
     \topsep\@hlskip \parsep\z@\partopsep\z@
     \trivlist \item\relax
     \if@minipage\else\vskip\parskip\fi
     \setbox\@tabfbox\hbox{%
       \rlap{\hskip\@totalleftmargin\indent\the\everypar}}%
     \def\@itemfudge{\box\@tabfbox}%
     \@startline\ignorespaces}

\newdimen\verbatimleftmargin
  \verbatimleftmargin\z@
\newdimen\verbatimbaselineskip
  \verbatimbaselineskip\baselineskip
\def\verbatimsize{\normalsize}

\def\@verbatim{%
 \topsep\z@ % \@hlskip
 \partopsep\z@\parsep\z@\itemsep\z@
 \trivlist \item\relax
  \if@minipage\else
   \vskip\baselineskip
   \vskip-\verbatimbaselineskip
   %\vskip\parskip
  \fi
  \leftskip\@totalleftmargin
  \if@minipage\else
   \advance \leftskip by \verbatimleftmargin
  \fi
  \rightskip\z@skip
  \parindent\z@\parfillskip\@flushglue\parskip\z@skip
  \@@par
  \@tempswafalse
  \def\par{%
    \if@tempswa
      \leavevmode \null \@@par\penalty\interlinepenalty
    \else
      \@tempswatrue
      \ifhmode\@@par\penalty\interlinepenalty\fi
    \fi}%
  \let\do\@makeother \dospecials
  \obeylines 
   \verbatimsize \baselineskip\verbatimbaselineskip
   \verbatim@font \@noligs
  \everypar \expandafter{\the\everypar \unpenalty}%
}
%\def\verbatim@font{\normalfont\ttfamily}

\newcounter{figure}
\renewcommand{\thefigure}{\@arabic\c@figure}
\def\fps@figure{tbp}
\def\ftype@figure{1}
\def\ext@figure{lof}
\if@ecaption
 \def\fnum@figure{\figurename~\thefigure}
 \def\fnum@efigure{Fig.\protect\,\thefigure.}
\else
 \def\fnum@figure{\figurename\protect\,\thefigure.}
\fi
\newenvironment{figure}
               {\@floatenv\capwidth72mm\if@ecaption\ecapwidth72mm\fi
                \abovecaptionskip1mm\belowcaptionskip\z@\@float{figure}}
               {\end@float}
\newenvironment{figure*}
               {\@floatenv
                \capwidth.8\textwidth\if@ecaption\ecapwidth.8\textwidth\fi
                \abovecaptionskip1mm\belowcaptionskip\z@\@dblfloat{figure}}
               {\end@dblfloat}
\newcounter{table}
\renewcommand{\thetable}{\@arabic\c@table}
\def\fps@table{tbp}
\def\ftype@table{2}
\def\ext@table{lot}
\if@ecaption
 \def\fnum@table{\tablename~\thetable}
 \def\fnum@etable{Table~\thetable.}
\else
 \def\fnum@table{\tablename\nobreakspace\thetable.}
\fi
\newenvironment{table}
               {\@floatenv\capwidth72mm\if@ecaption\ecapwidth72mm\fi
                \abovecaptionskip\z@\belowcaptionskip1.5mm\@float{table}}
               {\end@float}
\newenvironment{table*}
               {\@floatenv
                \capwidth.8\textwidth\if@ecaption\ecapwidth.8\textwidth\fi
                \abovecaptionskip\z@\belowcaptionskip1.5mm\@dblfloat{table}}
               {\end@dblfloat}

\def\@floatboxreset {%
        \reset@font
        \footnotesize\tabcolsep.5\zw
        \@setminipage
}

\def\@floatenv{\let\center\Center}

\def\Center{\topsep\z@\parsep\z@\partopsep\z@\itemsep\z@
 \trivlist \centering\item\relax}
\def\endCenter{\endtrivlist}

\long\def\@caption#1[#2]#3{\par
 \begingroup
  \@parboxrestore
  \if@minipage
   \@setminipage
  \fi
  % \if@ecaption
  %  \normalsize
  % \else
  %  \small
  % \fi
  \@makecaption{\csname fnum@#1\endcsname}{\ignorespaces #3}\par
 \endgroup}

\newdimen\abovecaptionskip
\newdimen\belowcaptionskip
\newdimen\capwidth

\def\ieej@shortstack{\@ifnextchar[\@ieej@shortstack{\@ieej@shortstack[c]}}
\def\@ieej@shortstack[#1]{%
  \leavevmode
  \vbox\bgroup
    %\baselineskip-\p@\lineskip 3\p@
    \let\mb@l\hss\let\mb@r\hss
    \expandafter\let\csname mb@#1\endcsname\relax
    \let\\\@stackcr
    \@ishortstack}

\if@ecaption
 \newdimen\ecapwidth
 \long\def\@makecaption#1#2{%
  \vskip\abovecaptionskip
   \belowcaptionskip1mm
   \def\capnum@font{\normalfont\sffamily}%
   \let\cap@font\relax
  \setbox\@tempboxa\hbox{\cap@font
   \ieej@shortstack[c]{{\capnum@font #1}\hskip1\zw #2}}%
  \@tempdima\ht\@tempboxa \advance \@tempdima \dp\@tempboxa
  \ifdim \@tempdima > \baselineskip
   \hfil\parbox[t]{\wd\@tempboxa}{\centering\baselineskip4mm\cap@font
    {\capnum@font #1}\hskip1\zw #2}%
  \else
   \ifdim \wd\@tempboxa > \capwidth
    \hfil\parbox[t]{\capwidth}{\centering\baselineskip4mm\cap@font
     {\capnum@font #1}\hskip1\zw #2}%
   \else
    \hbox to\hsize{\hfil\box\@tempboxa\hfil}%
   \fi
  \fi
  \vskip\belowcaptionskip
 }
 \long\def\ecaption#1{%
  \if@english
   \refstepcounter\@captype
   \vskip\abovecaptionskip
  \fi
  \bgroup
   \small
   \setbox\@tempboxa\hbox{%
    \ieej@shortstack[c]{\csname fnum@e\@captype\endcsname\hskip1em #1}}%
   \@tempdima\ht\@tempboxa \advance \@tempdima \dp\@tempboxa
   \ifdim \@tempdima > \baselineskip
    \hfil\parbox[t]{\wd\@tempboxa}{%
     \csname fnum@e\@captype\endcsname\hskip1em #1\strut}%
   \else
    \ifdim \wd\@tempboxa > \ecapwidth
     \hfil\parbox[t]{\ecapwidth}{%
      \csname fnum@e\@captype\endcsname\hskip1em #1\strut}%
    \else
     \hbox to\hsize{\hfil \box\@tempboxa\hfil}%
    \fi
   \fi
   \vspace{\belowcaptionskip}
  \egroup
 }
 \if@english
  \let\caption\ecaption
 \fi
\else
 \let\capnum@font\relax
 \let\cap@font\relax
 \long\def\@makecaption#1#2{%
  \small
  \vskip\abovecaptionskip
  \setbox\@tempboxa\hbox{\cap@font
   \ieej@shortstack[c]{{\capnum@font #1}\hskip1\zw #2}}%
  \@tempdima\ht\@tempboxa \advance \@tempdima \dp\@tempboxa
  \ifdim \@tempdima > 1.5\baselineskip
   \hfil\parbox[t]{\wd\@tempboxa}{\cap@font
    {\capnum@font #1}\hskip1\zw #2}%
  \else
   \ifdim \wd\@tempboxa > \capwidth
    \hfil\parbox[t]{\capwidth}{\cap@font
     {\capnum@font #1}\hskip1\zw #2}%
   \else
    \hbox to\hsize{\hfil\box\@tempboxa\hfil}%
   \fi
  \fi
  \vspace{\belowcaptionskip}%
 }
 %\let\ecaption\caption
\fi

\setlength\arraycolsep{5\p@}
\setlength\tabcolsep{.5\zw}
\setlength\arrayrulewidth{.12mm}
\setlength\doublerulesep{2\p@}
\setlength\tabbingsep{\labelsep}

\skip\@mpfootins = \skip\footins
\setlength\fboxsep{.5\zw}
\setlength\fboxrule{.1mm}

%% for 2.1.4 compatibility
%\@ifundefined{reDeclareMathAlphabet}{%
% \def\reDeclareMathAlphabet#1#2#3{%
%  \DeclareRobustCommand{#1}[1]{%
%    \ifmmode
%      \ifx\math@bgroup\@empty % 2.09 compatibility
%        #2\relax#3\relax##1\relax
%      \else % native mode
%        \ifx\math@bgroup\relax % oldstyle
%          #2\relax\@fontswitch\relax{#3}##1\relax
%        \else
%          #2{#3{##1}}%
%        \fi
%      \fi
%    \else
%      #2{##1}%
%    \fi
%  }%
% }%
% \@onlypreamble\reDeclareMathAlphabet
% }{}

\ifx\directlua\@undefined
\if@enablejfam
 \if@compatibility\else
   \DeclareSymbolFont{mincho}{\kenc@JYn}{mc}{m}{n}
   \DeclareSymbolFontAlphabet{\mathmc}{mincho}
   \SetSymbolFont{mincho}{bold}{\kenc@JYn}{gt}{m}{n}
   \jfam\symmincho
   \DeclareMathAlphabet{\mathgt}{\kenc@JYn}{gt}{m}{n}
 \fi
 \if@mathrmmc
   \AtBeginDocument{%
    \reDeclareMathAlphabet{\mathrm}{\mathrm}{\mathmc}
    \reDeclareMathAlphabet{\mathbf}{\mathbf}{\mathgt}
   }%
 \fi
\else
 \DeclareRobustCommand{\mathmc}{%
   \@latex@error{Command \noexpand\mathmc invalid with\space
      `disablejfam' class option.}\@eha
 }
 \DeclareRobustCommand{\mathgt}{%
   \@latex@error{Command \noexpand\mathgt invalid with\space
      `disablejfam' class option.}\@eha
 }
\fi
\fi

\DeclareOldFontCommand{\mc}{\normalfont\mcfamily}{\mathmc}
\DeclareOldFontCommand{\gt}{\normalfont\gtfamily}{\mathgt}
\DeclareOldFontCommand{\rm}{\normalfont\rmfamily}{\mathrm}
\DeclareOldFontCommand{\sf}{\normalfont\sffamily}{\mathsf}
\DeclareOldFontCommand{\tt}{\normalfont\ttfamily}{\mathtt}
\DeclareOldFontCommand{\bf}{\normalfont\bfseries}{\mathbf}
\DeclareOldFontCommand{\it}{\normalfont\itshape}{\mathit}
\DeclareOldFontCommand{\sl}{\normalfont\slshape}{\@nomath\sl}
\DeclareOldFontCommand{\sc}{\normalfont\scshape}{\@nomath\sc}
\DeclareRobustCommand*{\cal}{\@fontswitch\relax\mathcal}
\DeclareRobustCommand*{\mit}{\@fontswitch\relax\mathnormal}

%\newdimen\bibindent
%\setlength\bibindent{1.5em}
\newcommand{\newblock}{\hskip .11em\@plus.33em\@minus.07em}

\newdimen\abovebibsep \abovebibsep\z@

\newenvironment{thebibliography}[1]{%
 \raggedbottom
 \vskip-\prevdepth\prevdepth\z@
 \vskip7\@Q
 \vskip\abovebibsep
 \if@letter
 \else
  \vskip\baselineskip
 \fi
 \pagebreak[2]%
 \vbox to 10mm{%
  \vskip.5\baselineskip
  \hbox to \hsize{%
   \if@letter \normalsize\bfseries \else
    \sec@font\fi
   \hss\refname\hss}%
  \vss
  \hrule height .12mm
  \vskip.5\baselineskip
 }\par
 \nopagebreak
 \footnotesize\baselineskip13\@Q
 \list{\if@english (\hfil\@arabic\c@enumiv\hfil )\else
       \leavevmode\inhibitglue （\hfil\@arabic\c@enumiv\hfil ）\inhibitglue\fi}%
      {\leftmargin 4\zw
       \labelwidth 2\zw
       \labelsep 1\zw
       \topsep\z@\parsep\z@\partopsep\z@\itemsep\z@
       \usecounter{enumiv}%
       \let\p@enumiv\@empty
       \renewcommand\theenumiv{\@arabic\c@enumiv}%
      }%
      \sloppy
      \clubpenalty\z@
      \@clubpenalty\clubpenalty
      \widowpenalty\z@
      \sfcode`\.\@m}
  {\def\@noitemerr
    {\@latex@warning{Empty `thebibliography' environment}}%
   \endlist}

\renewcommand{\footnoterule}{%
  \kern-3\p@
  \hrule width \columnwidth
  \kern 2.6\p@}

\@addtoreset{footnote}{page}
\def\@makefnmark{\hbox{\kern\z@
 \@textsuperscript{\normalfont\@thefnmark}\kern\z@}}

\newcommand\@makefntext[1]{\Small
 \ifnum\c@footnote=\thr@@
  \@tempdima2\zw
 \else
  \ifnum\c@footnote=4\relax
   \@tempdima2.5\zw
  \else
   \@tempdima1.5\zw
  \fi
 \fi
 \parindent\@tempdima
 \noindent\hbox to \@tempdima{\hss\@makefnmark\hskip.25\zw}#1}

\def\thefootnote{\fnsymbol{footnote}}
% \def\@fnsymbol##1{\ensuremath{\ifcase##1\or
%  \dagger\or {\dagger}{\dagger}\or
%  {\dagger}{\dagger}{\dagger}\or {\dagger}{\dagger}{\dagger}{\dagger}\or
%  \dagger 5\or
%  \dagger 6\or 
%  \dagger 7\or \dagger 8\or \dagger 9\else\@ctrerr\fi}}%
%% used only in \maketitle
\def\@fnsymbol#1{%\ensuremath{
 \ifcase#1\or *\or **\or 
  ***\or ****\or 
  *{\scriptscriptstyle 5}\or *{\scriptscriptstyle 6}\or 
  *{\scriptscriptstyle 7}\or *{\scriptscriptstyle 8}\or 
  *{\scriptscriptstyle 9}\or *{\scriptscriptstyle 10}\or 
  *{\scriptscriptstyle 11}\or *{\scriptscriptstyle 12}\or
  \dagger\or \dagger\dagger\or \dagger\dagger\dagger\or
  \dagger\dagger\dagger\dagger
  \else
   \@ctrerr\fi}%}

\renewcommand{\theequation}{\@arabic\c@equation}
\def\@eqnnum{{\normalfont \normalcolor (\theequation)\hspace*{3.25mm}}}

\if@english
 \def\@begintheorem#1#2{%
  \topsep\z@\parsep\z@\partopsep\z@\itemsep\z@
   \trivlist\item[\hskip \labelsep{\bfseries #1\ #2}]}
 \def\@opargbegintheorem#1#2#3{%
  \topsep\z@\parsep\z@\partopsep\z@\itemsep\z@
   \trivlist\item[\hskip \labelsep{\bfseries #1\ #2\ (#3)}]}
\else
 \def\@begintheorem#1#2{%
  \settowidth{\labelwidth}{\inhibitglue 〔#1#2〕\inhibitglue}
  \begin{description}
  \item[\leavevmode\inhibitglue 〔#1#2〕\inhibitglue]}
 \def\@opargbegintheorem#1#2#3{\begin{description}
  \item[\leavevmode\inhibitglue 〔#1#2〕\inhibitglue （#3）\inhibitglue]}
  \def\@endtheorem{\end{description}}
 %\def\@thmcountersep{.}
\fi

\newif\if西暦 \西暦false
\def\西暦{\西暦true}
\def\和暦{\西暦false}
\def\today{{%
 \iftdir
   \if西暦
     \kansuji\number\year 年
     \kansuji\number\month 月
     \kansuji\number\day 日
   \else \@tempcnta\year
     \advance\@tempcnta-1988 平成
     \ifnum \@tempcnta =1 元\else\kansuji\number\@tempcnta\fi 年
     \kansuji\number\month 月\kansuji\number\day 日
   \fi
 \else
   \if西暦
     \number\year\, 年\hspace{.5em}\nobreak
     \number\month\, 月\hspace{.5em}\nobreak
     \number\day\, 日
   \else \@tempcnta\year
     \advance\@tempcnta-1988 平成
     \ifnum \@tempcnta =1 元\else\number\@tempcnta\fi
       \, 年\hspace{.5em}\nobreak
     \number\month\, 月\hspace{.5em}\nobreak\number\day\, 日
   \fi
 \fi}}

\if@english
 \newcommand{\refname}{References}
\else
 \newcommand{\refname}{文\hskip2\zw 献}
\fi
\if@ecaption
 \newcommand{\figurename}{図}
 \newcommand{\tablename}{表}
\else
 \newcommand{\figurename}{Fig.}
 \newcommand{\tablename}{Table}
\fi

%% from "citesort.sty", with a little customized
%\newcount\@minsofar
%\newcount\@min
%\newcount\@cite@temp
%\def\@citex[#1]#2{%
%\if@filesw \immediate \write \@auxout {\string \citation {#2}}\fi
%\@tempcntb\m@ne \let\@h@ld\relax \def\@citea{}%
%\@min\m@ne
%\@cite{%
%  \@for \@citeb:=#2\do {\@ifundefined {b@\@citeb}%
%    {\@h@ld\@citea\@tempcntb\m@ne{\bfseries ?}%
%    \@warning {Citation `\@citeb ' on page \thepage \space undefined}}%
%{\@minsofar\z@ \@for \@scan@cites:=#2\do {%
%  \@ifundefined{b@\@scan@cites}%
%    {\@cite@temp\m@ne}
%    {\@cite@temp\number\csname b@\@scan@cites \endcsname \relax}%
%\ifnum\@cite@temp > \@min% select the next one to list
%    \ifnum\@minsofar = \z@
%      \@minsofar\number\@cite@temp
%      \edef\@scan@copy{\@scan@cites}\else
%    \ifnum\@cite@temp < \@minsofar
%      \@minsofar\number\@cite@temp
%      \edef\@scan@copy{\@scan@cites}\fi\fi\fi}\@tempcnta\@min
%  \ifnum\@minsofar > \z@ % some more
%    \advance\@tempcnta\@ne
%    \@min\@minsofar
%    \ifnum\@tempcnta=\@minsofar %   Number follows previous--hold on to it
%      \ifx\@h@ld\relax
%        \edef \@h@ld{\@citea\csname b@\@scan@copy\endcsname}%
%      \else
%       \edef\@h@ld{\ifmmode{)\cite@f@t@(}\else)\cite@f@t@(\fi
%        \csname b@\@scan@copy\endcsname}%
%      \fi
%    \else \@h@ld\@citea\csname b@\@scan@copy\endcsname
%          \let\@h@ld\relax
%  \fi % no more
%\fi}%
%\def\@citea{)\penalty\@highpenalty\,(}}\@h@ld}{#1}}
%%% end of citesort.sty
%
%\def\cite@f@t@{%
% \if@english
%  --%
% \else
%  〜%
% \fi
%}
%
%%% from "cite.sty", with a little customized
%\def\@cite#1#2{\leavevmode\unskip
% \ifnum\lastpenalty=\z@\penalty\@M\fi % highpenalty before
% \smash{\kern\z@\,$^{\mbox{\normalfont\tiny
%  ({\multiply\@highpenalty 3 #1% % triple-highpenalties within
%      \if@tempswa,\penalty\@highpenalty\ #2\fi % and before note.
%    })}}$\kern\z@}\spacefactor\@m}
%%% end of cite.sty
%
%\let\org@cite\@cite
%\def\cite{\@ifnextchar[% ]
% {\@tempswatrue\let\@cite\org@cite\@citex}
% {\@tempswafalse\let\@cite\org@cite\@citex[]}}
%\def\Cite{\@ifnextchar[% ]
% {\@tempswatrue\let\@cite\@Cite\@citex}
% {\@tempswafalse\let\@cite\@Cite\@citex[]}}
%
%\def\@Cite#1#2{\leavevmode\unskip
%  \ifnum\lastpenalty=\z@\penalty\@highpenalty\fi% highpenalty before
%  \,({\multiply\@highpenalty 3 #1%             % triple-highpenalties within
%      \if@tempswa,\penalty\@highpenalty\ #2\fi % and before note.
%    })\spacefactor\@m}

\if@english
 \def\acknowledgment{\par
  \addpenalty{-\@highpenalty}%
  {\normalfont\bfseries Acknowledgment}\par
  \nopagebreak
 }
\else
 \def\acknowledgment{\par
  \addpenalty{-\@highpenalty}%
  {\normalfont\bfseries 謝\kern1\zw 辞}\par
  \nopagebreak
 }
\fi

\newdimen\abovebiosep \abovebiosep\z@
\newenvironment{biography}{%
 \vskip2\baselineskip
 \vskip\abovebiosep
 \if@english
  \Small\normalbaselineskip14\@Q\baselineskip14\@Q
 \else
  \Small\normalbaselineskip18\@Q\baselineskip18\@Q
 \fi
 }{\par}

\def\profile{\@ifstar{\n@profile}{\@profile}}
\def\eprofile{\@ifstar{\n@eprofile}{\@eprofile}}

\long\def\@profilecheck#1#2#3{%
 \if #1m \def\p@membership{\inhibitglue （正員）\inhibitglue}\else
  \if #1s \def\p@membership{\inhibitglue （学生員）\inhibitglue}\else
   \if #1n \def\p@membership{\inhibitglue （非会員）\inhibitglue}\else
    \if #1a \def\p@membership{\inhibitglue （准員）\inhibitglue}\else
     \if #1l \def\p@membership{\inhibitglue （終身会員）\inhibitglue}\else
      \if #1h \def\p@membership{\inhibitglue （名誉員）\inhibitglue}\else
       \if #1S \def\p@membership{\inhibitglue （上級会員）\inhibitglue}\else
        \if #1f \def\p@membership{\inhibitglue （フェロー）\inhibitglue}\else
  \def\p@membership{}%
  \ieej@warning{check the 1st. argument of \string\profile{#1}{#2}..}%
 \fi\fi\fi\fi\fi\fi\fi\fi
 \@temptokena{#2}%
 \def\hold@name{\the\@temptokena\unskip}%
 \chk@name{\the\@temptokena}%
 \setbox\@tempboxa\hbox{\get@oneword}%
  \ifdim \wd\@tempboxa=1\zw
   \setbox\@tempboxa\hbox{\spaceskip100mm #2}%
   \ifdim \wd\@tempboxa < 100mm
    \ieej@warning{Profile's name "#2" doesn't have a space}%
    \let\@tempx\hold@name
   \else
    \setbox\@tempboxc\hbox{#2}%
    \ifdim \wd\@tempboxc > 7\zw
     \def\@tempy##1 ##2\@nil{##1\hskip 1\zw ##2}%
    \else
     \def\@checkbox##1 ##2\@nil{%
      \setbox\@tempboxa\hbox{##1}\setbox\@tempboxb\hbox{##2}}%
     \edef\@tempcheck{\expandafter\@checkbox\the\@temptokena\@nil}\@tempcheck
     \def\@tempy##1 ##2\@nil{\leavevmode\hbox{%
      \ifdim \wd\@tempboxa < 3\zw
       \hbox to 3\zw{\ieej@kanjiskip{1\zw \@plus 1\zw}##1\hss}%
      \else
       \hbox to 3\zw{##1\hss}%
      \fi
      \hskip 1\zw
      \ifdim \wd\@tempboxb < 3\zw
       \hbox to 3\zw{\hss\ieej@kanjiskip{1\zw \@plus 1\zw}##2}%
      \else
       \hbox to 3\zw{\hss ##2}%
      \fi
     }}%
    \fi
     \edef\@tempx{\expandafter\@tempy\the\@temptokena\@nil}% \null
   \fi
  \else
   \let\@tempx\hold@name
  \fi
}

%\def\profile@font{\sffamily\gtfamily}
\let\profile@font\bfseries
\newcount\c@profile

\long\def\Profile#1#2#3{% for 外字 (\G)
 \advance \c@profile \@ne
 %%\@profilecheck{#1}{#2}{#3}%
 \if #1m \def\p@membership{\inhibitglue （正員）\inhibitglue}\else
  \if #1s \def\p@membership{\inhibitglue （学生員）\inhibitglue}\else
   \if #1n \def\p@membership{\inhibitglue （非会員）\inhibitglue}\else
    \if #1a \def\p@membership{\inhibitglue （准員）\inhibitglue}\else
     \if #1l \def\p@membership{\inhibitglue （終身会員）\inhibitglue}\else
      \if #1h \def\p@membership{\inhibitglue （名誉員）\inhibitglue}\else
       \if #1S \def\p@membership{\inhibitglue （上級会員）\inhibitglue}\else
        \if #1f \def\p@membership{\inhibitglue （フェロー）\inhibitglue}\else
  \def\p@membership{}%
  \ieej@warning{check the 1st. argument of \string\profile{#1}{#2}..}%
 \fi\fi\fi\fi\fi\fi\fi\fi
 \@temptokena{#2}%
 \def\hold@name{\the\@temptokena\unskip}%
 \let\@tempx\hold@name
 %%
 \parindent\z@
 \edef\@tempz{\@tempx}%
 \setbox\@tempboxa\hbox{\parbox[t]{\hsize}{\parshape=9 \z@ \hsize
  24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm 
  24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm \z@ \hsize
  \hskip1\zw{\profile@font \@tempz}\hskip1\zw\p@membership\hskip1\zw #3}}%
 \@tempdima\ht\@tempboxa \advance \@tempdima \dp\@tempboxa
 \output@profile
}

\long\def\@profile#1#2#3{%
 \advance \c@profile \@ne
 \@profilecheck{#1}{#2}{#3}%
 \parindent\z@
 \edef\@tempz{\@tempx}%
 \setbox\@tempboxa\hbox{\parbox[t]{\hsize}{\parshape=9 \z@ \hsize
  24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm 
  24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm \z@ \hsize
  \hskip1\zw{\profile@font \@tempz}\hskip1\zw\p@membership\hskip1\zw #3}}%
 \@tempdima\ht\@tempboxa \advance \@tempdima \dp\@tempboxa
 \output@profile
}

\long\def\n@profile#1#2#3{%
 \@profilecheck{#1}{#2}{#3}%
  \parindent 1\zw
  {\profile@font \@tempx}\hskip1\zw\p@membership\hskip1\zw #3
  \vskip2\baselineskip
}

\def\profile@mbrship#1#2{%
 \if #1m \def\p@membership{(Member)}\else
  \if #1s \def\p@membership{(Student Member)}\else
   \if #1n \def\p@membership{(Non-member)}\else
    \if #1a \def\p@membership{(Associate Member)}\else
     \if #1l \def\p@membership{(Life Member)}\else
      \if #1h \def\p@membership{(Honorary Member)}\else
       \if #1S \def\p@membership{(Senior Member)}\else
        \if #1f \def\p@membership{(Fellow)}\else
  \def\p@membership{}%
  \ieej@warning{check the 1st. argument of \string\profile{#1}{#2}..}%
 \fi\fi\fi\fi\fi\fi\fi\fi
}

\long\def\@eprofile#1#2#3{%
 \advance \c@profile \@ne
 \profile@mbrship{#1}{#2}%
 \parindent\z@
 \setbox\@tempboxa\hbox{\parbox[t]{\hsize}{\parshape=11 \z@ \hsize
  24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm 
  24.75mm 59.73mm 24.75mm 59.73mm
  24.75mm 59.73mm 24.75mm 59.73mm 24.75mm 59.73mm \z@ \hsize
  \hskip1\zw{\bfseries #2}\hskip1\zw\p@membership\hskip1\zw #3}}%
 \@tempdima\ht\@tempboxa \advance \@tempdima \dp\@tempboxa
 \output@profile
}

\long\def\n@eprofile#1#2#3{%
 \profile@mbrship{#1}{#2}%
 \parindent 1\zw
 {\bfseries #2}\hskip1\zw\p@membership\hskip1\zw #3%
 \vskip2\baselineskip
}

\if@english
 \let\profile\eprofile
\fi

\def\output@profile{%
  \ifdim \@tempdima < \if@english 9\else 8\fi\baselineskip
   \vtop to 35.25mm{%
    \leavevmode\smash{\rlap{\profile@box}}%
     \hbox to \hsize{\hss\box\@tempboxa\hss}\vss
    }%
  \else
   \leavevmode\smash{\rlap{\profile@box}}%
    \hbox to \hsize{\hss\box\@tempboxa\hss}%
  \fi
  \vskip2\baselineskip
}

\def\profile@box{%
 \IfFileExists{a\the\c@profile.\ieej@in@ext}%
  {\lower30.5mm\hbox{%
    \resizebox{22mm}{28mm}{\includegraphics{a\the\c@profile.\ieej@in@ext}}}%
  }%
  {\l@p@box}%
}

\def\l@p@box{%
 \lower30.5mm
 \vbox to 28mm{\hrule height .1mm
  \hbox to 22mm{%
   \vrule width .1mm height 27.8mm
    \hss
   \vrule width .1mm height 27.8mm}%
 \hrule height .1mm}%
}

%%% </borrowed from dotseqn.sty by Donald Arseneau>
%%\ProvidesPackage{dotseqn}
%%  [1995/03/22  v1.1 \space Dots leading to equation numbers]
\newcommand\EqnDots{\leaders\hbox{%
 $\m@th \mkern1.5mu\cdot\mkern1.5mu$}\hfill}
\@ifundefined{mathindent}{\newdimen\mathindent \mathindent\leftmargini}{}
\renewcommand{\[}{\relax \ifmmode\@badmath \else
 \begin{trivlist}%
  \@beginparpenalty\predisplaypenalty \@endparpenalty\postdisplaypenalty
  \item[]\leavevmode \hbox to\linewidth\bgroup $\m@th\displaystyle %$
  \hskip\mathindent\bgroup
 \fi}
\renewcommand{\]}{\relax\ifmmode \egroup $\hfil% $
    \egroup \end{trivlist}%
  \else \@badmath \fi}
\renewenvironment{equation}%
 {\@beginparpenalty\predisplaypenalty \@endparpenalty\postdisplaypenalty
     \refstepcounter{equation}\trivlist \item[]\leavevmode
       \hbox to\linewidth\bgroup $\m@th% $
         \displaystyle \hskip\mathindent}%
 {$\EqnDots % $   Replace `\hfil' with dotted leaders `\EqnDots'.
     \displaywidth\linewidth\hbox{\@eqnnum}\egroup \endtrivlist}
\renewenvironment{eqnarray}{%
   \stepcounter{equation}%
   \def\@currentlabel{\p@equation\theequation}%
   \global\@eqnswtrue \m@th \global\@eqcnt\z@  \tabskip\mathindent
   \let\\\@eqncr \setlength\abovedisplayskip\topsep
   \ifvmode \addtolength\abovedisplayskip\partopsep \fi
   \addtolength\abovedisplayskip\parskip
   \setlength\belowdisplayskip\abovedisplayskip
   \setlength\belowdisplayshortskip\abovedisplayskip
   \setlength\abovedisplayshortskip\abovedisplayskip
   $$\everycr{}\halign to\linewidth% $$
   \bgroup
     \hskip\@centering
     $\displaystyle\tabskip\z@skip{##}$\@eqnsel&%
     \global\@eqcnt\@ne \hfil${\DEQ@acs##\DEQ@acs}$\hfil&%
     \global\@eqcnt\tw@ $\displaystyle{##}$\hskip\@centering\cr%
 }% end of "\begin" part
 {\@@eqncr
   \noalign{% vertical skip up to overlay phantom line
      \penalty\@M \vskip-\prevdepth
      \edef\@tempa{\omit\span\omit\span\omit   % span three columns
        \vrule\@depth\the\prevdepth \@width\z@ % strut of proper depth
        \kern-\mathindent \kern\linewidth}%    % full line width
      \nointerlineskip \expandafter % use saved |\@tempa| outside group
   }\@tempa\cr
   \egroup
   \global\advance\c@equation\m@ne$$% $$
   \global\@ignoretrue
 }

%% from latex.ltx
%\def\@@eqncr{\let\reserved@a\relax
%    \ifcase\@eqcnt \def\reserved@a{& & &}\or \def\reserved@a{& &}%
%     \or \def\reserved@a{&}\else
%       \let\reserved@a\@empty
%       \@latex@error{Too many columns in eqnarray environment}\@ehc\fi
%     \reserved@a \if@eqnsw\@eqnnum\stepcounter{equation}\fi
%     \global\@eqnswtrue\global\@eqcnt\z@\cr}
%%

\def\@@eqncr{\let\reserved@a\@empty
   \ifcase\@eqcnt \def\reserved@a{& &}\or \def\reserved@a{&}\fi
   \reserved@a
   \if@eqnsw \egroup $\EqnDots \@eqnnum $\bgroup \stepcounter{equation}%
   \fi \global\@eqnswtrue\global\@eqcnt\z@\cr}
\def\DEQ@acs{\hskip\tw@\arraycolsep}
\DeclareOption{leftjust}{\let\@eqnsel\hfil}
\DeclareOption{nocolsep}{\let\DEQ@acs\null}
\ExecuteOptions{nocolsep}% {leftjust}% 
\ProcessOptions
%% </borrowed from dotseqn.sty>

\def\FRAC#1#2{\leavevmode\kern-.1em
  \raise.5ex\hbox{\the\scriptfont0 #1}\kern-.1em
  /\kern-.1em\lower.25ex\hbox{\the\scriptfont0 #2}}
\DeclareRobustCommand\RN[1]{\uppercase\expandafter{\romannumeral#1}}
\def\onelineskip{\vskip\baselineskip}
\def\halflineskip{\vskip.5\baselineskip}
\DeclareRobustCommand\MARU[1]{\raisebox{0.1\zh}%
 {{\normalfont\ooalign{\hfil\lower.168ex\hbox{#1}\hfil\crcr\mathhexbox20D}}}}
\DeclareRobustCommand\kintou[2]{\leavevmode\hbox to #1{%
 \ieej@kanjiskip{\z@ \@plus 1fill \@minus 1fill}%
 \ieej@xkanjiskip{\z@ \@plus 1fill \@minus 1fill}#2\hfil}%
}
\DeclareRobustCommand\ddash{\leavevmode\hbox to 2\zw{---\hss ---}}
\def\ruby#1#2{\leavevmode \setbox0=\hbox{#1}\setbox1=\hbox{\tiny#2}%
 \ifdim\wd0>\wd1 \dimen0=\wd0 \else \dimen0=\wd1 \fi
 \hbox{\ieej@kanjiskip{\fill}%
  \vbox{\smash{\hbox to \dimen0{\tiny \hfil#2\hfil}}%
   \nointerlineskip \hbox to \dimen0{\hfil#1\hfil}}}}
\def\QED{{\unskip\nobreak\hfil\penalty50
 \hskip1\zw\hbox{}\nobreak\hfil \hbox{$\Box$\hskip1\zw}
 \parfillskip\z@ \finalhyphendemerits\z@\par}}

\ifx\directlua\@undefined
\postbreakpenalty`（=10000
\prebreakpenalty`）=10000
\postbreakpenalty`［=10000
\prebreakpenalty`］=10000
\postbreakpenalty`〈=10000
\prebreakpenalty`〉=10000
\prebreakpenalty`"=10000
\prebreakpenalty`℃=10000
\prebreakpenalty`　=10000
\prebreakpenalty`・=10000
\prebreakpenalty`〜=10000
\prebreakpenalty`ー=10000
\prebreakpenalty`？=10000
\prebreakpenalty`！=10000
\if@enable@uptex
 \postbreakpenalty16=10000
\else 
 \postbreakpenalty"5C=10000
\fi
\postbreakpenalty`【=10000
\prebreakpenalty`】=10000
\postbreakpenalty`〔=10000
\prebreakpenalty`〕=10000
\postbreakpenalty`『=10000
\prebreakpenalty`』=10000
\inhibitxspcode`〒=2
\inhibitxspcode`！=1
\else
\ltjsetparameter{prebreakpenalty={`，,10000}}
\ltjsetparameter{prebreakpenalty={`。,10000}}
\ltjsetparameter{prebreakpenalty={`、,10000}}
\ltjsetparameter{prebreakpenalty={`．,10000}}
\ltjsetparameter{prebreakpenalty={`）,10000}}
\ltjsetparameter{prebreakpenalty={`」,10000}}
\ltjsetparameter{prebreakpenalty={`』,10000}}
\ltjsetparameter{prebreakpenalty={`］,10000}}
\ltjsetparameter{prebreakpenalty={`〉,10000}}
\ltjsetparameter{prebreakpenalty={`〕,10000}}
\ltjsetparameter{prebreakpenalty={`】,10000}}
\ltjsetparameter{prebreakpenalty={`〜,10000}}
\ltjsetparameter{prebreakpenalty={`…,10000}}
\ltjsetparameter{prebreakpenalty={`・,10000}}
\ltjsetparameter{prebreakpenalty={`ー,10000}}
\ltjsetparameter{prebreakpenalty={`！,10000}}
\ltjsetparameter{prebreakpenalty={`？,10000}}
\ltjsetparameter{postbreakpenalty={`（,10000}}
\ltjsetparameter{postbreakpenalty={`「,10000}}
\ltjsetparameter{postbreakpenalty={`『,10000}}
\ltjsetparameter{postbreakpenalty={`［,10000}}
\ltjsetparameter{postbreakpenalty={`〈,10000}}
\ltjsetparameter{postbreakpenalty={`〔,10000}}
\ltjsetparameter{postbreakpenalty={`【,10000}}
\ltjsetparameter{jaxspmode={`\{,1}}
\ltjsetparameter{jaxspmode={`\},2}}
\ltjsetparameter{jaxspmode={`!,2}}
\ltjsetparameter{jaxspmode={`〒,1}}
\ltjsetparameter{alxspmode={`+,3}}
\ltjsetparameter{alxspmode={`\%,3}}
\ltjsetparameter{jcharwidowpenalty=500}
\fi

\def\sloppy{\tolerance9999\hbadness9999\hfuzz.5\p@ \vfuzz.5\p@}

\hbadness4000
\vbadness10001
\tolerance4000\pretolerance\m@ne
\clubpenalty\z@
\widowpenalty\z@

\pagestyle{IEEJ}
\pagenumbering{arabic}
\raggedbottom
\if@twocolumn
  \twocolumn
% \sloppy
  \flushbottom
\else
  \onecolumn
\fi
\if@twoside
  \@mparswitchtrue
\else
  \@mparswitchfalse
\fi

%\AtEndDocument{%
% \clearpage
% \addtocounter{page}{-1}%
% \immediate\write\@auxout
%  {\string\newlabel{ieej@lastpage}{{}{\thepage}}}%
% %%\addtocounter{page}{1}%
%}

\AtBeginDocument{%
 \displaywidowpenalty\z@
 \interdisplaylinepenalty\z@
 \predisplaypenalty\z@
 \postdisplaypenalty\z@
 %%
 \RequirePackage{lastpage}%
 \@ifundefined{directlua}{}{%
  \unless\ifltj@disablejfam
   \reDeclareMathAlphabet{\mathrm}{\mathrm}{\mathmc}%
   \reDeclareMathAlphabet{\mathbf}{\mathbf}{\mathgt}%
  \fi
 }%
 %%
 %\@ifundefined{cmex@opt}{%
 % \DeclareFontFamily{OMX}{cmex}{}{}%
 % \DeclareFontShape{OMX}{cmex}{m}{n}{%
 %  <->    cmex10
 % }{}%
 %}{%
 % \ifnum\cmex@opt=7\relax
 %  \DeclareFontFamily{OMX}{cmex}{}{}%
 %  \DeclareFontShape{OMX}{cmex}{m}{n}{%
 %   <->    cmex10
 %  }{}%
 % \fi
 %}%
 %% graphicx
 \@ifpackageloaded{graphics}{}{\RequirePackage{graphicx}}%
 %% cite.sty +\Cite
 \@ifpackageloaded{cite}{%
  %% Superscript cite
  %\renewcommand\citeleft{(}% -> superscript のときは無効
  %\renewcommand\citeright{)}% -> superscript のときは無効
  %%\providecommand\citepunct{,\penalty\citepunctpenalty%
  %%      \hskip.13emplus.1emminus.1em\relax}%
  \renewcommand\citepunct{\penalty\citepunctpenalty}%
  \renewcommand\citeform[1]{(#1)}%
  \if@english
   \renewcommand\citedash{--}%
  \else
   \renewcommand\citedash{〜}%
  \fi
  %\def\@citess#1{\mbox{$\m@th^{\hbox{\OverciteFont{#1}}}$}}%
  \if@english\else
   \def\@citess#1{\kern\z@
    \mbox{$\m@th^{\hbox{\OverciteFont{#1}}}$}}%
  \fi
  %% \Cite is same as \citen
  \DeclareRobustCommand{\Cite}{%
   \renewcommand\citeleft{}%
   \renewcommand\citeright{}%
   \@ifnextchar[%]
    {\@tempswatrue\@citex}{\@tempswafalse\@citex[]}}%
 }{}%
 %% amsmath-2018-12-01.sty
 \@ifpackageloaded{amsmath}{%
   %\@mathmargin\mathindent
   \@mathmargin2\zw \@plus\z@ \@minus\z@
   \multlinegap1\zw
   \def\maketag@@@#1{\hbox{\m@th\normalfont #1}\hskip3.25mm}%
   \renewcommand{\eqref}[1]{\textup{\tagform@{\ref{#1}}\unskip}}%
   \def\make@display@tag{%
    \if@eqnsw
        \incr@eqnum %%\print@eqnum
        \EqnDots\tagform@\theequation %%!!
    \else
        \iftag@
            \df@tag
            \global\let\df@tag\@empty
        \fi
    \fi
    \ifmeasuring@
    \else
      \ifx\df@label\@empty\else
        \@xp\ltx@label\@xp{\df@label}%
        \global\let\df@label\@empty
      \fi
    \fi
   }%
  }{}%
 %% amsthm
 \@ifpackageloaded{amsthm}{%
  %% \thm@preskip=\topsep \thm@postskip=\thm@preskip と定義済み
  %% [] の中のパーレンを全角に/後ろのピリを削除/head の後ろを一字空きに
  \def\@thm#1#2#3{%
    \ifhmode\unskip\unskip\par\fi
    \normalfont
    \trivlist
    \hangindent1\zw
    \let\thmheadnl\relax
    \let\thm@swap\@gobble
    %\thm@notefont{\fontseries\mddefault\upshape}%
    \thm@notefont{\bfseries}%
    \thm@headpunct{}% add period after heading
    %\thm@headsep 5\p@ plus\p@ minus\p@\relax
    \thm@headsep 1\zw \@plus .15\zw \@minus .25\zw\relax
    %\thm@space@setup
    \thm@preskip=\z@ %\topsep
    \thm@postskip=\thm@preskip
    #1% style overrides
    \@topsep \thm@preskip               % used by thm head
    \@topsepadd \thm@postskip           % used by \@endparenv
    \def\@tempa{#2}\ifx\@empty\@tempa
      \def\@tempa{\@oparg{\@begintheorem{#3}{}}[]}%
    \else
      \refstepcounter{#2}%
      \def\@tempa{\@oparg{\@begintheorem{#3}{\csname the#2\endcsname}}[]}%
    \fi
    \@tempa
  }%
  %\def\@endtheorem{\endtrivlist \@doendpe}% \@endpefalse void
  \def\th@plain{% style=plain
   %\itshape % body font
  }%
  \def\th@remark{% style=remark
   \thm@headfont{\bfseries}%
   \normalfont % body font
   %\thm@preskip\topsep \divide\thm@preskip\tw@
   %\thm@postskip\thm@preskip
  }%
  %% 半角パーレンを全角に
  \def\thmhead@plain#1#2#3{%
    \if@english\else
    \leavevmode\inhibitglue 〔\fi
     \thmname{#1}\thmnumber{%
     \@ifnotempty{#1}{ }\@upn{#2}}%
    \if@english\else
     〕\inhibitglue\fi
    \thmnote{{\the\thm@notefont （#3）\inhibitglue}}}%
  \let\thmhead\thmhead@plain
  %% \swapnumbers が展開されたとき有効に
  \def\swappedhead#1#2#3{%
    \thmnumber{#2}%
    \thmname{\@ifnotempty{#2}{~}#1}%
    \thmnote{ {\the\thm@notefont （#3）\inhibitglue}}}%
  %% proof
  \def\proofname{\textbf{証明}}%
  \renewenvironment{proof}[1][\proofname]{\par
    %\@tempdimb\prevdepth
    %\ifdim \@tempdimb=0.0001pt % 直前に GrayBox など
    % \vspace{-\topsep}
    %\fi
    \pushQED{\qed}%
    \normalfont
    %\topsep6\p@\@plus6\p@\relax
    \labelsep1\zw
    \trivlist
    \item[\hskip\labelsep
          %\itshape
      \textbf{#1\inhibitglue}\@addpunct{}]\ignorespaces
  }{%
    \popQED
    \endtrivlist\@endpefalse
  }%
 }{}%
 %% nidanfloat
 \@ifpackageloaded{nidanfloat}{%
  \renewcommand\dblbotfraction{0.9}% 0.5
  \setcounter{dblbotnumber}{4}% 2
 }{}%
 %%
 \if@foreword
  \@ifundefined{definecolor}{%
   \IfFileExists{xcolor.sty}%
    {\RequirePackage{xcolor}%
     \definecolor{LXXgray}{gray}{0.3}}%
    {\ieej@warning{xcolor package is required.^^J
     \string\usepackage\string{xcolor\string}}}%
  }{\definecolor{LXXgray}{gray}{0.3}}%
 \fi
 %\if@ExSum
 % \small
 % \baselineskip16\@Q
 %\fi
 \if@essay
  \def\HeadLogo{エ\hskip-.175\zw ッ\hskip-.175\zw セ\hskip-.075\zw イ}%
  %\def\head@title{エッセイ}%
 \fi
 %% for txfonts (newtxtext は ntxtlf)
 %\def\tmp@rmdefault{txr}%
 %\ifx\rmdefault\tmp@rmdefault
 % \DeclareFontShape{\kenc@JYn}{txtt}{bx}{n}{<->ssub*gt/m/n}{}%
 % \DeclareFontShape{\kenc@JTn}{txtt}{bx}{n}{<->ssub*gt/m/n}{}%
 %\fi
 %% eps/pdf
 \@ifundefined{ver@dvips.def}{\def\ieej@in@ext{pdf}}{\def\ieej@in@ext{eps}}%
 %% newtxtext, nfssext-cfr and superiors redefine \@makefnmark.
 \@ifundefined{sustyle}{}{%
  \def\@makefnmark{\hbox{\kern\z@
   \@textsuperscript{\normalfont\@thefnmark}\kern\z@}}%
 }%
}

\endinput
