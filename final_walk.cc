#include "lslmini.hh"
#include <map>
#include <vector>

void LLASTNode::final_walk() {
   LLASTNode *node;
   final_pre_checks();
   for ( node = get_children(); node; node = node->get_next() )
      node->final_walk();
   final_post_checks();
}

bool allret(LLASTNode *p) {
   bool ret = false;
   if (p->get_node_type() == NODE_STATEMENT && p->get_node_sub_type() == NODE_RETURN_STATEMENT) {
      // TODO check next value here for unreachable code
      return true;
   }
   else if (p->get_node_type() == NODE_STATEMENT && p->get_node_sub_type() == NODE_IF_STATEMENT) {
      bool true_branch = p->get_child(1) && allret(p->get_child(1));
      bool false_branch = p->get_child(2) && allret(p->get_child(2));

      return (true_branch && false_branch);
   }
   else if (p->get_node_type() == NODE_STATEMENT && p->get_node_sub_type() == NODE_COMPOUND_STATEMENT) {
      LLASTNode *q;
      for (q = p->get_children(); q; q = q->get_next()) {
         ret |= allret(q);
      }
   }
   else {
#if 0
      if (p->get_next()) {
         ret |= allret(p->get_next());
      }
      if (p->get_children()) {
         ret |= allret(p->get_children());
      }
#endif
   }
   return ret;
}

void LLScriptGlobalFunction::final_pre_checks() {
   LLScriptIdentifier *id = (LLScriptIdentifier *) get_child(0);
   //LLScriptFunctionDec *decl = (LLScriptFunctionDec *) get_child(1);
   LLScriptStatement *statement = (LLScriptStatement *) get_child(2);

   if (id->get_symbol() == NULL) {
      id->resolve_symbol(SYM_FUNCTION);
   }

   if (id->get_symbol() != NULL) {
      LLScriptType *type = id->get_symbol()->get_type();

      if (type->get_itype() != LST_NULL && !allret(statement)) {
         ERROR(IN(get_child(0)), E_NOT_ALL_PATHS_RETURN);
      }
   }
}

static bool isKey(const char *value) {
   if (strlen(value) != 36 || value[8] != '-' || value[13] != '-' || value[18] != '-' || value[23] != '-')
      return false;

   char buf[37];
   strcpy(buf, value);
   // change dashes to valid letters, and check the whole string
   buf[8] = 'A'; buf[13] = 'A'; buf[18] = 'A'; buf[23] = 'A';
   return strspn(buf, "0123456789ABCDEFabcdef") == 36;
}

void check_cond(LLScriptExpression *expr, bool warn_if_true) {
   // a syntax error can leave a null node here; it is not an expression
   if (expr == NULL || expr->get_node_type() != NODE_EXPRESSION) return;
   // see if expression is constant
   if ( expr->get_constant_value() != NULL ) {
      int truth = 2; // 2 denotes that it hasn't been handled
      LLNodeSubType type = expr->get_constant_value()->get_node_sub_type();
      if ( type == NODE_INTEGER_CONSTANT ) {
         truth = ((LLScriptIntegerConstant*)expr->get_constant_value())->get_value() != 0;
      } else if ( type == NODE_FLOAT_CONSTANT ) {
         truth = ((LLScriptFloatConstant*)expr->get_constant_value())->get_value() != 0.f;
      } else if ( type == NODE_STRING_CONSTANT ) {
         truth = ((LLScriptStringConstant*)expr->get_constant_value())->get_value()[0] != 0;
      } else if ( type == NODE_KEY_CONSTANT) {
         const char *value = ((LLScriptKeyConstant*)expr->get_constant_value())->get_value();
         truth = value && isKey(value) && strcmp(value, "00000000-0000-0000-0000-000000000000");
      } else if ( type == NODE_VECTOR_CONSTANT ) {
         LLVector *value = ((LLScriptVectorConstant*)expr->get_constant_value())->get_value();
         truth = value->x != 0.f || value->y != 0.f || value->z != 0.f;
      } else if ( type == NODE_QUATERNION_CONSTANT ) {
         LLQuaternion *value = ((LLScriptQuaternionConstant*)expr->get_constant_value())->get_value();
         truth = value->x != 0.f || value->y != 0.f || value->z != 0.f || value->s != 1.0f;
      } else if ( type == NODE_LIST_CONSTANT ) {
         int length = ((LLScriptListConstant*)expr->get_constant_value())->get_length();
         truth = length > (mono_mode ? 0 : 1);
      } else {
         // you can't handle the truth
      }

      if (truth != 2) {
         // valid
         if (truth) {
            if (warn_if_true) {
               ERROR( IN(expr), W_CONDITION_ALWAYS_TRUE );
            }
         } else {
            ERROR( IN(expr), W_CONDITION_ALWAYS_FALSE );
         }
      }
   }

   // see if expression is an assignment
   if ( expr->get_operation() == '=' ) {
      ERROR( IN(expr), W_ASSIGNMENT_IN_COMPARISON );
   }
}

static void check_sibling_writes(LLASTNode *first, const char *what);

void LLScriptListExpression::final_pre_checks() {
   LLASTNode *elem;
   for ( elem = get_children(); elem; elem = elem->get_next() )
      if ( elem->get_type()->get_itype() == LST_LIST )
          ERROR( IN(elem), E_LIST_IN_LIST );
   check_sibling_writes( get_children(), "list elements" );
}

void LLScriptFunctionExpression::final_pre_checks() {
   check_sibling_writes( get_child(1), "function arguments" );
}

void LLScriptVectorExpression::final_pre_checks() {
   check_sibling_writes( get_children(), "vector components" );
}

void LLScriptQuaternionExpression::final_pre_checks() {
   check_sibling_writes( get_children(), "rotation components" );
}

void LLScriptListConstant::final_pre_checks() {
   LLASTNode *elem;
   for ( elem = get_children(); elem; elem = elem->get_next() ) {
      if ( elem->get_type()->get_itype() == LST_LIST ) {
         if (elem->get_node_type() == NODE_SIMPLE_ASSIGNABLE) {
            ERROR( IN(elem->get_child(0)), E_LIST_IN_LIST );
         } else {
            ERROR( IN(elem), E_LIST_IN_LIST );
         }
      }
   }
}

void LLScriptTypecastExpression::final_pre_checks() {
   if (!mono_mode && get_type()->get_itype() == LST_LIST) {
      // Check if it only has a variable of type string or key
      LLASTNode *child = get_children();
      if (child && !child->get_next() && child->get_node_type() == NODE_EXPRESSION && child->get_node_sub_type() == NODE_LVALUE_EXPRESSION) {
         // We're on the right track. Go one level deeper.
         child = child->get_children();
         if (child && !child->get_next() && child->get_node_type() == NODE_IDENTIFIER) {
            LST_TYPE type = child->get_type()->get_itype();
            // A-ha!
            if (type == LST_STRING) {
                ERROR(HERE, W_KEY_OR_STR_TO_LIST, "string", "key", "string");
            }  else if (type == LST_KEY) {
                ERROR(HERE, W_KEY_OR_STR_TO_LIST, "key", "string", "key");
            }
         }
      }

   }
}

void LLScriptIfStatement::final_pre_checks() {
   check_cond((LLScriptExpression*)get_child(0), true);
}

void LLScriptWhileStatement::final_pre_checks() {
   check_cond((LLScriptExpression*)get_child(0), false);
}

void LLScriptDoStatement::final_pre_checks() {
   check_cond((LLScriptExpression*)get_child(1), false);
}

void LLScriptForStatement::final_pre_checks() {
   check_cond((LLScriptExpression*)get_child(1), false);
}

void LLScriptEventHandler::final_pre_checks() {
   LLASTNode *node = NULL;
   bool is_last = true;
   int found = 0;
   LLScriptIdentifier *id = (LLScriptIdentifier *)get_child(0);

   // check for duplicates
   for (node = get_parent()->get_children(); node; node = node->get_next()) {
      if ( node->get_node_type() != NODE_EVENT_HANDLER )
         continue;
      LLScriptIdentifier *other_id = (LLScriptIdentifier *)node->get_child(0);
      if (!strcmp(id->get_name(), other_id->get_name())) {
         found++;
         is_last = (node == this);
      }
   }
   if (found > 1 && is_last) {
      ERROR( HERE, E_MULTIPLE_EVENT_HANDLERS, id->get_name() );
   }

   // check parameters
   if (id->get_symbol() == NULL) {
      id->resolve_symbol(SYM_EVENT);
   }

   if (id->get_symbol() != NULL) {
      // check argument types
      LLScriptFunctionDec       *function_decl;
      LLScriptIdentifier        *declared_param_id;
      LLScriptIdentifier        *passed_param_id;
      int                        param_num = 1;

      function_decl         = id->get_symbol()->get_function_decl();
      declared_param_id     = (LLScriptIdentifier*) function_decl->get_children();
      passed_param_id       = (LLScriptIdentifier*) get_child(1)->get_children();

      while ( declared_param_id != NULL && passed_param_id != NULL ) {
         if ( !passed_param_id->get_type()->can_coerce(
                  declared_param_id->get_type()) ) {
            ERROR( IN(passed_param_id), E_ARGUMENT_WRONG_TYPE_EVENT,
                  passed_param_id->get_type()->get_node_name(),
                  param_num,
                  id->get_name(),
                  declared_param_id->get_type()->get_node_name(),
                  declared_param_id->get_name()
                 );
            return;
         }
         passed_param_id   = (LLScriptIdentifier*) passed_param_id->get_next();
         declared_param_id = (LLScriptIdentifier*) declared_param_id->get_next();
         ++param_num;
      }

      if ( passed_param_id != NULL ) {
         // printf("too many, extra is %s\n", passed_param_id->get_name());
         ERROR( IN(passed_param_id), E_TOO_MANY_ARGUMENTS_EVENT, id->get_name() );
      } else if ( declared_param_id != NULL ) {
         // printf("too few, extra is %s\n", declared_param_id->get_name());
         ERROR( HERE, E_TOO_FEW_ARGUMENTS_EVENT, id->get_name() );
      }
   }
   else {
      ERROR( HERE, E_INVALID_EVENT, id->get_name());
   }

}

void LLScriptSwitchStatement::final_pre_checks() {
   int num_defaults = 0;
   LLASTNode *node = get_children(), *node2, *second_default = NULL;

   // first child is switch expression
   if (node->get_constant_value() != NULL) {
      // rather than warning on each case, warn once at the top
      ERROR( IN(node), W_CONSTANT_SWITCH );
   }
   LLScriptType *switch_type = node->get_type();
   if (switch_type->get_itype() == LST_LIST) {
      // This error may sound a bit awkward to the user, but since == is
      // used internally by the switch converter, it should be OK.
      ERROR( IN(node), W_LIST_COMPARE );
   }

   // subsequent children are case or default blocks
   for (node = node->get_next() ; node; node = node->get_next() ) {
      // node is a case block or a default block (default blocks have NULL
      // as the first child)
      if (node->get_child(0)->get_node_type() != NODE_NULL) {
         LLScriptConstant *const1 = node->get_child(0)->get_constant_value();
         if (const1) {
            // check type compatibility
            if (switch_type->get_result_type(EQ, const1->get_type())) {

               // compare every case block with every other case block
               // (skipping default blocks)
               for ( node2 = node->get_next(); node2; node2 = node2->get_next() ) {
                  if (node2->get_child(0)) {
                     LLScriptConstant *const2 = node2->get_child(0)->get_constant_value();
                     if (const2) {
                        LLScriptIntegerConstant *comparison = (LLScriptIntegerConstant *)const1->operation(EQ, const2, const1->get_lloc());
                        if (comparison) {
                           if (comparison->get_value()) {
                              ERROR( IN(const2), W_DUPLICATE_CASE );
                           } // else it will err later, as type equality is transitive
                           delete comparison;
                        }
                     }
                  }
               }

            } else {
               ERROR( IN(const1), E_INCOMPATIBLE_CASE_TYPE );
            }

         }
      } else {
         if (++num_defaults == 2) {
            second_default = node;
         }
      }
   }
   if (! num_defaults) {
      ERROR( HERE, W_SWITCH_NO_DEFAULT );
   } else if (num_defaults > 1) {
      ERROR( IN(second_default), E_SWITCH_MULTIPLE_DEFAULTS );
   }

   script->inc_switchlevel();
}

void LLScriptSwitchStatement::final_post_checks() {
   script->dec_switchlevel();
}

void LLScriptBreakStatement::final_pre_checks() {
   if (!script->get_switchlevel()) {
      ERROR( HERE, E_BREAK_WITHOUT_SWITCH );
   }
}

// -s: side effects in && / || operands.
//
// LSL evaluates both operands of && and || unconditionally, and the right
// operand first. C-style guards such as `if (x != 0 && f(x))' therefore do not
// prevent f() from running. Report operands whose evaluation is observable or
// can fail, so nobody relies on short-circuit behaviour that LSL does not have.

static bool is_effect_free_builtin(const char *name) {
   // Functions that act although their name says otherwise (queue pop, timer
   // reset, dataserver request). A forced delay alone is not an effect: the
   // script stalls but nothing changes, so llGetParcelPrimOwners (2.0 s),
   // llModPow (1.0 s) and llXorBase64Strings (0.3 s) stay effect-free.
   static const char *acting_exact[] = {
      "llGetNextEmail", "llGetAndResetTime", "llGetNotecardLine", "llGetNumberOfNotecardLines",
      "llGetSimulatorHostname",
      NULL
   };
   // Effect-free functions whose name does not match a prefix below.
   static const char *pure_exact[] = {
      "llAvatarOnSitTarget", "llAvatarOnLinkSitTarget", "llGround", "llGroundContour",
      "llGroundNormal", "llGroundSlope", "llScriptDanger", "llListFindStrided", "llVerifyRSA",
      "llSignRSA", "llLinear2sRGB", "llsRGB2Linear", "llGetNotecardLineSync",
      NULL
   };
   // Builtins that only return a value: they change no script, object or world
   // state and start no request (they may be random). Prefix match.
   static const char *pure_prefixes[] = {
      "llGet", "llDetected", "llList2", "llListFindList", "llListSort", "llListStatistics",
      "llListRandomize", "llListInsertList", "llListReplaceList", "llDeleteSub",
      "llInsertString", "llSubStringIndex", "llStringLength", "llStringTrim",
      "llStringToBase64", "llBase64To", "llIntegerToBase64", "llXorBase64", "llToUpper",
      "llToLower", "llCSV2List", "llParseString", "llDumpList2String", "llEscapeURL",
      "llUnescapeURL", "llChar", "llOrd", "llHash", "llMD5String", "llSHA", "llHMAC",
      "llComputeHash", "llJson", "llReplaceSubString", "llAbs", "llFabs", "llFloor",
      "llCeil", "llRound", "llSqrt", "llPow", "llLog", "llSin", "llCos", "llTan", "llAtan2",
      "llAsin", "llAcos", "llModPow", "llFrand", "llVec", "llRot2", "llRotBetween",
      "llEuler2Rot", "llAxes2Rot", "llAxisAngle2Rot", "llAngleBetween", "llSameGroup",
      "llOverMyLand", "llKey2Name", "llName2Key", "llIsFriend", "llAgentInExperience",
      "llEdgeOfWorld", "llWater", "llWind", "llCloud", "llLinksetDataRead",
      "llLinksetDataCount", "llLinksetDataListKeys", "llLinksetDataFindKeys",
      "llLinksetDataAvailable", "llGenerateKey", "llIsLinkGLTFMaterial",
      NULL
   };
   int i;
   for (i = 0; acting_exact[i]; ++i) {
      if (strcmp(name, acting_exact[i]) == 0) return false;
   }
   for (i = 0; pure_exact[i]; ++i) {
      if (strcmp(name, pure_exact[i]) == 0) return true;
   }
   for (i = 0; pure_prefixes[i]; ++i) {
      if (strncmp(name, pure_prefixes[i], strlen(pure_prefixes[i])) == 0) return true;
   }
   return false;
}

// Returns a description of the first thing in the subtree that acts or can fail, or NULL.
// Nested && / || expressions are skipped: they report their own operands.
static const char *find_effect_or_failure(LLASTNode *node) {
   LLASTNode *child;
   int op;
   if (node == NULL) return NULL;
   if (node->get_node_type() == NODE_EXPRESSION) {
      op = ((LLScriptExpression *)node)->get_operation();
      // A nested && or || reports its own operands.
      if (op == BOOLEAN_AND || op == BOOLEAN_OR) return NULL;
      if (node->get_node_sub_type() == NODE_FUNCTION_EXPRESSION) {
         LLScriptIdentifier *id = (LLScriptIdentifier *)node->get_child(0);
         LLScriptSymbol *symbol = id ? id->get_symbol() : NULL;
         if (symbol == NULL) return NULL;   // undeclared or deprecated: already reported as an error
         if (symbol->get_sub_type() != SYM_BUILTIN) return "Call to a user function (it may act or fail)";
         if (!is_effect_free_builtin(id->get_name())) return "Call to a builtin that acts";
      } else {
         switch (op) {
            case '=': case ADD_ASSIGN: case SUB_ASSIGN: case MUL_ASSIGN: case DIV_ASSIGN: case MOD_ASSIGN:
               return "Assignment";
            case INC_OP: case DEC_OP: case POSTINC_OP: case POSTDEC_OP:
               return "Increment or decrement";
            case '/': case '%':
               {
                  // Only a number divisor can raise a Math Error, and only when it can be zero.
                  LLASTNode *divisor = node->get_child(1);
                  LLScriptConstant *c = divisor ? divisor->get_constant_value() : NULL;
                  LST_TYPE t = (divisor && divisor->get_type()) ? divisor->get_type()->get_itype() : LST_NULL;
                  if (t != LST_INTEGER && t != LST_FLOATINGPOINT) break;
                  if (c && c->get_node_sub_type() == NODE_INTEGER_CONSTANT && ((LLScriptIntegerConstant *)c)->get_value() != 0) break;
                  if (c && c->get_node_sub_type() == NODE_FLOAT_CONSTANT && ((LLScriptFloatConstant *)c)->get_value() != 0.0f) break;
                  return "Division or modulo (can raise a Math Error)";
               }
         }
      }
   }
   for (child = node->get_children(); child; child = child->get_next()) {
      const char *found = find_effect_or_failure(child);
      if (found) return found;
   }
   return NULL;
}

void LLScriptExpression::final_pre_checks() {
   const char *found;
   LLASTNode *lhs;
   LLASTNode *rhs;
   const char *op;
   if (!warn_side_effects) return;
   if (operation != BOOLEAN_AND && operation != BOOLEAN_OR) return;
   op = operation == BOOLEAN_AND ? "&&" : "||";
   lhs = get_child(0);
   rhs = get_child(1);
   found = find_effect_or_failure(rhs);
   if (found) ERROR( IN(rhs), W_SIDE_EFFECT_IN_LOGICAL_OP, found, "right", op );
   found = find_effect_or_failure(lhs);
   if (found) ERROR( IN(lhs), W_SIDE_EFFECT_IN_LOGICAL_OP, found, "left", op );
}

// -s, second rule: the order in which LSL evaluates the arguments of a call, the
// elements of a list and the components of a vector or rotation is not
// documented. A variable written in one of them (assignment, ++, --) and read
// or written in another gives a result that depends on that order.

// The global variables each user function writes, directly or through the
// user functions it calls; filled once per script before the walk.
typedef std::map<std::string, std::set<std::string> > NameSets;
static NameSets global_writes_of;

// `v' for a variable, `v.x' for one of its components.
static std::string use_key(LLScriptIdentifier *id) {
   std::string key = id->get_name();
   if (id->get_member()) {
      key += ".";
      key += id->get_member();
   }
   return key;
}

static LLScriptIdentifier *assignment_target(LLASTNode *node) {
   LLASTNode *target;
   int op = ((LLScriptExpression *)node)->get_operation();
   switch (op) {
      case '=': case ADD_ASSIGN: case SUB_ASSIGN: case MUL_ASSIGN: case DIV_ASSIGN: case MOD_ASSIGN:
      case INC_OP: case DEC_OP: case POSTINC_OP: case POSTDEC_OP:
         target = node->get_child(0);
         if (target && target->get_node_type() == NODE_EXPRESSION
             && target->get_node_sub_type() == NODE_LVALUE_EXPRESSION)
            target = target->get_child(0);
         if (target && target->get_node_type() == NODE_IDENTIFIER)
            return (LLScriptIdentifier *)target;
   }
   return NULL;
}

static LLScriptIdentifier *called_user_function(LLASTNode *node) {
   LLScriptIdentifier *id;
   if (node->get_node_sub_type() != NODE_FUNCTION_EXPRESSION) return NULL;
   id = (LLScriptIdentifier *)node->get_child(0);
   if (id == NULL || id->get_symbol() == NULL || id->get_symbol()->get_sub_type() == SYM_BUILTIN) return NULL;
   return id;
}

// Direct writes to globals and calls to user functions inside one function body.
static void collect_global_writes(LLASTNode *node, std::set<std::string> &writes, std::set<std::string> &calls) {
   LLASTNode *child;
   LLScriptIdentifier *id;
   if (node == NULL) return;
   if (node->get_node_type() == NODE_EXPRESSION) {
      id = assignment_target(node);
      if (id && id->get_symbol() && id->get_symbol()->get_sub_type() == SYM_GLOBAL)
         writes.insert(id->get_name());
      id = called_user_function(node);
      if (id) calls.insert(id->get_name());
   }
   for (child = node->get_children(); child; child = child->get_next())
      collect_global_writes(child, writes, calls);
}

static void collect_functions(LLASTNode *node, NameSets &calls_of) {
   LLASTNode *child;
   LLScriptIdentifier *id;
   if (node == NULL) return;
   if (node->get_node_type() == NODE_GLOBAL_FUNCTION) {
      id = (LLScriptIdentifier *)node->get_child(0);
      if (id) collect_global_writes(node->get_child(2), global_writes_of[id->get_name()], calls_of[id->get_name()]);
      return;
   }
   for (child = node->get_children(); child; child = child->get_next())
      collect_functions(child, calls_of);
}

void LLScriptScript::final_pre_checks() {
   NameSets calls_of;
   NameSets::iterator f;
   std::set<std::string>::iterator c;
   bool changed = true;
   global_writes_of.clear();
   if (!warn_side_effects) return;
   collect_functions(this, calls_of);          // the global storages are siblings under the script node
   while (changed) {                       // a function also writes what the functions it calls write
      changed = false;
      for (f = calls_of.begin(); f != calls_of.end(); ++f) {
         std::set<std::string> &mine = global_writes_of[f->first];
         for (c = f->second.begin(); c != f->second.end(); ++c) {
            if (*c == f->first) continue;          // a recursive call adds nothing
            std::set<std::string> &theirs = global_writes_of[*c];
            size_t before = mine.size();
            mine.insert(theirs.begin(), theirs.end());
            if (mine.size() != before) changed = true;
         }
      }
   }
}

// Names the subtree writes (assignment targets, the globals of the user functions it calls)
// and reads (every variable, by component when one is named).
static void collect_variable_uses(LLASTNode *node, std::set<std::string> &reads, std::set<std::string> &writes) {
   LLASTNode *child;
   LLScriptIdentifier *id;
   LLScriptSymbol *symbol;
   NameSets::iterator f;
   if (node == NULL) return;
   if (node->get_node_type() == NODE_EXPRESSION) {
      id = assignment_target(node);
      if (id) writes.insert(use_key(id));
      id = called_user_function(node);
      if (id && (f = global_writes_of.find(id->get_name())) != global_writes_of.end()) {
         writes.insert(f->second.begin(), f->second.end());
         reads.insert(f->second.begin(), f->second.end());
      }
   } else if (node->get_node_type() == NODE_IDENTIFIER) {
      symbol = ((LLScriptIdentifier *)node)->get_symbol();
      if (symbol && symbol->get_symbol_type() == SYM_VARIABLE)
         reads.insert(use_key((LLScriptIdentifier *)node));
   }
   for (child = node->get_children(); child; child = child->get_next())
      collect_variable_uses(child, reads, writes);
}

static std::string base_of(const std::string &key) {
   size_t dot = key.find('.');
   return dot == std::string::npos ? key : key.substr(0, dot);
}

static void check_sibling_writes(LLASTNode *first, const char *what) {
   std::vector<LLASTNode *> siblings;
   std::vector<std::set<std::string> > uses;       // keys a sibling reads or writes (`v' or `v.x')
   std::vector<std::set<std::string> > writes;
   std::map<std::string, int> users;               // siblings using each key
   std::map<std::string, int> whole_users;         // siblings using a variable as a whole
   std::map<std::string, int> member_users;        // siblings using one of its components
   std::set<std::string>::iterator name;
   std::set<std::string> seen;
   LLASTNode *node;
   size_t i;
   if (!warn_side_effects || first == NULL || first->get_next() == NULL) return;
   for (node = first; node; node = node->get_next()) {
      std::set<std::string> reads;
      siblings.push_back(node);
      writes.push_back(std::set<std::string>());
      collect_variable_uses(node, reads, writes.back());
      reads.insert(writes.back().begin(), writes.back().end());
      uses.push_back(reads);
      seen.clear();
      for (name = reads.begin(); name != reads.end(); ++name) {
         std::string base = base_of(*name);
         users[*name] += 1;
         if (base == *name) whole_users[base] += 1;
         else if (seen.insert(base).second) member_users[base] += 1;
      }
   }
   for (i = 0; i < siblings.size(); ++i) {
      for (name = writes[i].begin(); name != writes[i].end(); ++name) {
         std::string base = base_of(*name);
         bool conflict;
         if (base == *name) {
            // the whole variable: another sibling using it, or one of its components, conflicts
            bool mine = false;
            std::set<std::string>::iterator k;
            for (k = uses[i].begin(); k != uses[i].end() && !mine; ++k)
               mine = *k != base && base_of(*k) == base;
            conflict = users[*name] > 1 || member_users[base] > (mine ? 1 : 0);
         } else {
            // one component: the same component elsewhere, or the whole variable elsewhere
            conflict = users[*name] > 1 || whole_users[base] > (uses[i].count(base) ? 1 : 0);
         }
         if (conflict)
            ERROR( IN(siblings[i]), W_SIBLING_WRITE_ORDER, name->c_str(), what );
      }
   }
}
