// An explicit UI subset, not a replacement for the PixInsight imaging engine.
var __objects = [];
function __init(obj, kind, parent) {
    obj.__id = __bridge.create(kind, parent && parent.__id !== undefined ? parent.__id : -1);
    __objects[obj.__id] = obj;
    obj.dialog = kind === 'Dialog' ? obj : parent ? parent.dialog : null;
    ['text','title','windowTitle','toolTip','enabled','visible','checked','currentItem','value',
     'minWidth','minHeight','maxWidth','maxHeight','margin','spacing','width','height'].forEach(function(name) {
        Object.defineProperty(obj,name,{get:function(){return __bridge.get(obj.__id,name);},
            set:function(value){__bridge.set(obj.__id,name,value);},configurable:true});
    });
    Object.defineProperty(obj,'sizer',{set:function(value){this.__sizer=value;__bridge.set(obj.__id,'sizer',value.__id);},
        get:function(){return this.__sizer;},configurable:true});
    ['show','hide','ok','cancel','adjustToContents','execute'].forEach(function(name){
        obj[name]=function(){return __bridge.call(obj.__id,name,null);};
    });
    obj.setMinWidth=function(v){obj.minWidth=v;};
    obj.setMinHeight=function(v){obj.minHeight=v;};
    obj.setFixedWidth=function(v){obj.minWidth=v;obj.maxWidth=v;};
    obj.setFixedHeight=function(v){obj.minHeight=v;obj.maxHeight=v;};
    obj.setScaledMinWidth=obj.setMinWidth; obj.setScaledMinHeight=obj.setMinHeight;
    obj.setScaledFixedWidth=obj.setFixedWidth; obj.setScaledFixedHeight=obj.setFixedHeight;
    obj.logicalPixelsToPhysical=function(v){return v;};
    obj.add=function(child,stretch){__bridge.add(obj.__id,child.__id,stretch||0);};
    obj.addStretch=function(v){__bridge.stretch(obj.__id,v||1);};
    obj.addSpacing=function(v){__bridge.call(obj.__id,'addSpacing',v);};
    obj.addItem=function(v){__bridge.call(obj.__id,'addItem',v);};
    obj.setRange=function(a,b){__bridge.call(obj.__id,'setRange',[a,b]);};
    obj.setValue=function(v){obj.value=v;};
    obj.setPrecision=function(v){__bridge.call(obj.__id,'setPrecision',v);};
}
function Dialog(p){__init(this,'Dialog',p);}
function Control(p){__init(this,'Control',p);}
function Label(p){__init(this,'Label',p);}
function PushButton(p){__init(this,'PushButton',p);}
function ToolButton(p){__init(this,'ToolButton',p);}
function CheckBox(p){__init(this,'CheckBox',p);}
function RadioButton(p){__init(this,'RadioButton',p);}
function GroupBox(p){__init(this,'GroupBox',p);}
function ComboBox(p){__init(this,'ComboBox',p);}
function Edit(p){__init(this,'Edit',p);}
function NumericControl(p){__init(this,'NumericControl',p);var self=this;this.label={};
    Object.defineProperty(this.label,'text',{get:function(){return self.title;},set:function(v){self.title=v;}});}
function NumericEdit(p){__init(this,'NumericEdit',p);}
function VerticalSizer(){__init(this,'VerticalSizer');}
function HorizontalSizer(){__init(this,'HorizontalSizer');}
function MessageBox(text,title){this.execute=function(){return __bridge.message(String(text),String(title||'PixInsight'));};}
var console={writeln:function(v){__bridge.log(String(v));},write:function(v){__bridge.log(String(v));},
    show:function(){},hide:function(){},flush:function(){}};
var StdButton_Ok=1, StdButton_Cancel=2, StdIcon_Information=1, StdIcon_Warning=2, StdIcon_Error=3;
var TextAlign_Left=1, TextAlign_Right=2, TextAlign_HorzCenter=4, TextAlign_VertCenter=128;
function format(text){var args=arguments,i=1;return text.replace(/%[dfs]/g,function(){return String(args[i++]);});}
