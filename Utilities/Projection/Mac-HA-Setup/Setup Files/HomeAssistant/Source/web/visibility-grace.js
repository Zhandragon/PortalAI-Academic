// Wall-clock checks also expire a suspended page whose timers did not run.
export class VisibilityGrace {
  constructor(expire,{now=()=>Date.now(),setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id)}={}) {
    Object.assign(this,{expire,now,setTimer,clearTimer});this.deadline=0;this.timer=null;
  }
  reset(){this.clearTimer(this.timer);this.timer=null;this.deadline=0;}
  allowed(){
    if(this.deadline&&this.now()>=this.deadline){this.reset();this.expire();return false;}
    return true;
  }
  change(hidden){
    if(!this.allowed())return false;
    if(!hidden){this.reset();return true;}
    if(!this.deadline){this.deadline=this.now()+10000;this.timer=this.setTimer(()=>this.allowed(),10000);}
    return true;
  }
}
